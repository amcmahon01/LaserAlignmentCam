import sys
import logging
import argparse
import warnings

from PyQt6 import QtCore
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot, QObject, QSize, QItemSelection

import pyqtgraph as pg
from pyqtgraph.dockarea import Dock, DockArea

from camera import USB_Camera, Camera_Search
from util import *


class Viewer(QMainWindow):
    save_opts = pyqtSignal(str)
    logging_sig = pyqtSignal(str)
    closing_sig = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running_threads = RunningThreads()
        self.closing_sig.connect(self.finished)
        self.ready_to_close = False
        self.closing = False
        self.searching = False

        self.active_cams = {}

        parser = argparse.ArgumentParser(description="Utility for acquiring data from ICI Thermal Cameras on a timed interval.")
        parser.add_argument("-s", "--start", action="store_true", help="Start acquisition")
        parser.add_argument("-o", "--output_path", type=str, default="./data", help="Path to store acquired data")
        parser.add_argument("-i", "--framerate", type=float, default=60, help="Framerate")
        parser.add_argument("-b", "--binary", action="store_true", help="Save binary files")
        parser.add_argument("-j", "--jpg", action="store_true", help="Save JPG files")
        parser.add_argument("-t", "--tiff", action="store_true", help="Save TIFF files")
        parser.add_argument("-n", "--min_value", type=float, default=0, help="Min value for JPG scale")
        parser.add_argument("-m", "--max_value", type=float, default=45, help="Max value for JPG scale")
        #Not implemeneted
        #parser.add_argument("-s", "--serial", nargs='+', type=str, default='*', help="Cameras to use (identified by serial #)")       
        self.args = parser.parse_args()

        self.widgets = self.initUI()

    def initUI(self):
        self.dock_area = DockArea()
        self.setCentralWidget(self.dock_area)
        self.resize(1280,800)
        self.setWindowTitle('Laser Alignment Cam')

        #Shared panels
        self.dock_config = Dock("Configuration", size=(300, 450))
        self.dock_stats = Dock("Statistics", size=(300, 250))
        self.dock_console = Dock("Console", size=(800,100))
        self.dock_cam_placeholder = Dock("Cameras", size=(900,700)) #placeholder

        #Configuration
        self.createConfiguration()
        self.dock_config.addWidget(self.config_widget)
        self.dock_config.setFixedWidth(300)
        self.dock_config.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        #Stats
        self.stats_tree = QTreeWidget()
        self.stats_tree.setColumnCount(2)
        self.stats_tree.setColumnWidth(0, 120)
        self.stats_tree.setHeaderHidden(True)
        self.dock_stats.addWidget(self.stats_tree)

        #Console
        self.createConsole()
        self.dock_console.addWidget(self.console_widget)

        self.dock_area.addDock(self.dock_config, 'left')
        self.dock_area.addDock(self.dock_stats, 'bottom', self.dock_config)
        self.dock_area.addDock(self.dock_console, 'right')
        self.dock_area.addDock(self.dock_cam_placeholder, 'top', self.dock_console)

        #Acqusition timer
        # self.acq_timer = QTimer()
        # self.acq_timer.setInterval(int(self.ui_framerate.value() * 1000))
        # self.acq_timer.timeout.connect(QApplication.processEvents)
        # self.ui_framerate.valueChanged.connect(lambda new_val : self.acq_timer.setInterval(int(new_val * 1000)))

        #Callbacks
        self.btn_search_for_cams.clicked.connect(self.searchForCams)
        self.btn_shutdown_all.clicked.connect(self.camShutdownAll)

        # self.btn_acq_startstop.clicked.connect(self.acqStartStop)
        # self.btn_browse.clicked.connect(self.selectDataFolder)

        #Finally, init cams
        self.searchForCams()

        # #Auto-start from command line (Note, this may occur before cams are found. This is ok, they will begin when inited.)
        # if self.args.start:
        #     self.acqStartStop()

    def createConfiguration(self):
        self.config_widget = QWidget()
        self.config_widget.setObjectName(u"Configuration")
        self.config_widget.resize(800, 600)
        self.config_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.verticalLayout = QVBoxLayout(self.config_widget)
        self.verticalLayout.setObjectName(u"verticalLayout")

        #Cameras
        self.groupBox_cameras = QGroupBox(self.config_widget)
        self.groupBox_cameras.setObjectName(u"groupBox_cameras")
        self.groupBox_cameras.setTitle("Cameras")
        self.groupBox_cameras.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.layout_cameras = QVBoxLayout(self.groupBox_cameras)

        #Camera Table
        self.camera_table = QTableWidget(self.groupBox_cameras)
        self.camera_table.setObjectName(u"camera_table")
        self.camera_table.setFixedSize(251,200)
        self.camera_table.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.camera_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.camera_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.camera_table.setColumnCount(4)
        self.camera_table.horizontalHeader().setDefaultSectionSize(50)
        self.camera_table.horizontalHeader().setStretchLastSection(True)
        #self.camera_table.selectionModel().selectionChanged.connect(self.cameraSelChanged)

        item0 = QTableWidgetItem()
        item0.setText("Enabled") 
        self.camera_table.setHorizontalHeaderItem(0, item0)

        item1 = QTableWidgetItem()
        item1.setText("Type") 
        self.camera_table.setHorizontalHeaderItem(1, item1)

        item2 = QTableWidgetItem()
        item2.setText("Status") 
        self.camera_table.setHorizontalHeaderItem(2, item2)
        self.camera_table.setColumnWidth(2, 65)

        item3 = QTableWidgetItem()
        item3.setText("Size") 
        self.camera_table.setHorizontalHeaderItem(3, item3)

        self.layout_cameras.addWidget(self.camera_table)

        #Global Camera Buttons
        self.camera_buttons = QWidget(self.groupBox_cameras)
        self.camera_buttons.setObjectName(u"camera_buttons")
        self.camera_buttons.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.camera_btn_layout = QGridLayout(self.camera_buttons)

        self.btn_shutdown_all = QPushButton(self.camera_buttons)
        self.btn_shutdown_all.setObjectName(u"btn_shutdown_all")
        self.btn_shutdown_all.setText("Shutdown All") 
        self.btn_shutdown_all.setFixedSize(QSize(111,24))
        self.camera_btn_layout.addWidget(self.btn_shutdown_all, 0, 1, Qt.AlignmentFlag.AlignCenter)

        self.btn_search_for_cams = QPushButton(self.camera_buttons)
        self.btn_search_for_cams.setObjectName(u"btn_search_for_cams")
        self.btn_search_for_cams.setText("Search for Cameras") 
        self.btn_search_for_cams.setFixedSize(QSize(111,24))
        self.camera_btn_layout.addWidget(self.btn_search_for_cams, 0, 0, Qt.AlignmentFlag.AlignCenter)

        self.layout_cameras.addWidget(self.camera_buttons)
        self.verticalLayout.addWidget(self.groupBox_cameras)

        # #Selected Camera Buttons
        # self.gb_sel_cameras = QGroupBox(self.config_widget)
        # self.gb_sel_cameras.setObjectName(u"gb_sel_cameras")
        # self.gb_sel_cameras.setTitle("Selected Camera")
        # self.gb_sel_cameras.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # self.gb_sel_cameras.setEnabled(False)

        # self.sel_camera_btn_layout = QGridLayout(self.gb_sel_cameras)

        # self.btn_stop_selected = QPushButton(self.gb_sel_cameras)
        # self.btn_stop_selected.setObjectName(u"btn_stop_selected")
        # self.btn_stop_selected.setText("Stop Selected")
        # self.btn_stop_selected.setFixedSize(QSize(111,24))
        # self.sel_camera_btn_layout.addWidget(self.btn_stop_selected, 1, 1, Qt.AlignmentFlag.AlignCenter)

        # self.btn_start_selected = QPushButton(self.gb_sel_cameras)
        # self.btn_start_selected.setObjectName(u"btn_start_selected")
        # self.btn_start_selected.setText("Start Selected")
        # self.btn_start_selected.setFixedSize(QSize(111,24))
        # self.sel_camera_btn_layout.addWidget(self.btn_start_selected, 1, 0, Qt.AlignmentFlag.AlignCenter)

        # self.cb_enable_nuc = QCheckBox(self.gb_sel_cameras)
        # self.cb_enable_nuc.setObjectName(u"cb_enable_nuc")
        # self.cb_enable_nuc.setText("Enable Auto-NUC")
        # self.cb_enable_nuc.setChecked(True)
        # self.sel_camera_btn_layout.addWidget(self.cb_enable_nuc, 2, 0, Qt.AlignmentFlag.AlignCenter)

        # self.btn_nuc = QPushButton(self.gb_sel_cameras)
        # self.btn_nuc.setObjectName(u"btn_nuc")
        # self.btn_nuc.setText("Run NUC Now")
        # self.btn_nuc.setFixedSize(QSize(111,24))
        # self.sel_camera_btn_layout.addWidget(self.btn_nuc, 3, 0, Qt.AlignmentFlag.AlignCenter)

        # self.rb_high_gain = QRadioButton("High Gain")
        # self.rb_high_gain.setObjectName(u"rb_high_gain")
        # self.rb_high_gain.setChecked(False)
        # self.sel_camera_btn_layout.addWidget(self.rb_high_gain, 2, 1, Qt.AlignmentFlag.AlignCenter)

        # self.rb_low_gain = QRadioButton("Low Gain")
        # self.rb_low_gain.setObjectName(u"rb_low_gain")
        # self.rb_low_gain.setChecked(True)
        # self.sel_camera_btn_layout.addWidget(self.rb_low_gain, 3, 1, Qt.AlignmentFlag.AlignCenter)

        # self.rbg_gain = QButtonGroup()
        # self.sel_camera_btn_layout.addWidget(self.rb_low_gain, 3, 1, Qt.AlignmentFlag.AlignCenter)
        # self.rbg_gain = QButtonGroup()
        # self.rbg_gain.addButton(self.rb_high_gain)
        # self.rbg_gain.addButton(self.rb_low_gain)

        # self.verticalLayout.addWidget(self.gb_sel_cameras)

        #Acqusition
        self.gb_acqusition = QGroupBox(self.config_widget)
        self.gb_acqusition.setObjectName(u"gb_acqusition")
        self.gb_acqusition.setTitle("Acquisition Settings")
        self.gb_acqusition.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.acq_layout = QGridLayout(self.gb_acqusition)
        self.acq_layout.setObjectName(u"acq_layout")

        self.cb_auto_range = QCheckBox(self.gb_acqusition)
        self.cb_auto_range.setObjectName(u"cb_auto_range")
        self.cb_auto_range.setText("Auto Range")
        self.cb_auto_range.setChecked(True)
        self.acq_layout.addWidget(self.cb_auto_range, 0, 0, Qt.AlignmentFlag.AlignLeft)

        self.cb_auto_levels = QCheckBox(self.gb_acqusition)
        self.cb_auto_levels.setObjectName(u"cb_auto_levels")
        self.cb_auto_levels.setText("Auto Levels")
        self.cb_auto_levels.setChecked(True)
        self.acq_layout.addWidget(self.cb_auto_levels, 1, 0, Qt.AlignmentFlag.AlignLeft)

        self.cb_auto_hist = QCheckBox(self.gb_acqusition)
        self.cb_auto_hist.setObjectName(u"cb_auto_hist")
        self.cb_auto_hist.setText("Auto Histogram Range")
        self.cb_auto_hist.setChecked(True)
        self.acq_layout.addWidget(self.cb_auto_hist, 2, 0, Qt.AlignmentFlag.AlignLeft)

        self.verticalLayout.addWidget(self.gb_acqusition)

        # self.btn_acq_startstop = QPushButton(self.groupBox_acquisition)
        # self.btn_acq_startstop.setObjectName(u"btn_acq_startstop")
        # self.btn_acq_startstop.setText("Start")
        # self.acq_layout.addWidget(self.btn_acq_startstop, 0, 0, Qt.AlignmentFlag.AlignLeft)

        # self.label_framerate = QLabel(self.groupBox_acquisition)
        # self.label_framerate.setObjectName(u"label_framerate")
        # self.label_framerate.setText("Frame Rate:") 
        # self.acq_layout.addWidget(self.label_framerate, 0, 1, Qt.AlignmentFlag.AlignRight)

        # self.ui_framerate = QDoubleSpinBox(self.groupBox_acquisition)
        # self.ui_framerate.setObjectName(u"ui_interval")
        # self.ui_framerate.setValue(self.args.framerate)
        # self.acq_layout.addWidget(self.ui_framerate, 0, 2, Qt.AlignmentFlag.AlignLeft)

        # #Save Options
        # self.btn_save_png = QPushButton(self.groupBox_acquisition)
        # self.btn_save_png.setObjectName(u"cb_save_binary")
        # self.btn_save_png.setFixedSize(QSize(111,24))
        # self.btn_save_png.setText("Save Snapshot") 

        # self.save_cb_layout = QVBoxLayout()
        # self.save_cb_layout.addWidget(self.btn_save_png)
        # self.acq_layout.addLayout(self.save_cb_layout, 1, 0, Qt.AlignmentFlag.AlignLeft)

        # #Data Path
        # self.ui_datapath = QLineEdit(self.groupBox_acquisition)
        # self.ui_datapath.setObjectName(u"ui_datapath")
        # self.ui_datapath.setText(self.args.output_path)
        # self.acq_layout.addWidget(self.ui_datapath)

        # self.label_datapath = QLabel(self.groupBox_acquisition)
        # self.label_datapath.setObjectName(u"label_datapath")
        # self.label_datapath.setText("Data Path:") 
        # self.acq_layout.addWidget(self.label_datapath)

        # self.btn_browse = QPushButton(self.groupBox_acquisition)
        # self.btn_browse.setObjectName(u"btn_browse")
        # self.btn_browse.setText("Browse") 
        # self.acq_layout.addWidget(self.btn_browse)

        # self.verticalLayout.addWidget(self.groupBox_acquisition)

        return self.config_widget
        
    def createConsole(self):
        self.console_widget = QTextEdit(self)
        self.console_widget.setFont(QFont("Courier New", 8))
        self.console_widget.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.console_widget.setReadOnly(True)

        console_handler = QSignalHandler(self.logging_sig)
        console_handler.setFormatter(logging.Formatter('[%(levelname)-10s] (%(threadName)-10s), %(asctime)s, %(message)s'))
        console_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(console_handler)
        self.logging_sig.connect(self.console_widget.append)

        return self.console_widget

    @pyqtSlot()
    def searchForCams(self):
        if not self.searching:
            logging.info("Searching for cameras...")
            self.searching = True
            self.cam_search = Camera_Search(list(self.active_cams.keys()))
            self.cam_search.result.connect(self.initCams)
            self.cam_search.q_thread.start()
            self.cam_search.deleteLater()

    def createImageView(self, img):
        imv = pg.ImageView()
        imv.setPredefinedGradient('turbo') #'CET-R4')
        imv.setImage(img)
        return imv

    @pyqtSlot(list)
    def initCams(self, cam_list):
        self.searching = False
        for idx, cam in enumerate(cam_list):
            if idx in self.active_cams:
                continue    #skip existing
            self.active_cams[idx] = {"name": cam}

            #Update UI
            if self.camera_table.rowCount() < len(self.active_cams) + 1:
                self.camera_table.insertRow(idx)

            cam_cb_widget = QWidget()
            cam_cb_layout = QHBoxLayout(cam_cb_widget)
            cam_cb = QCheckBox()
            cam_cb.setText(str(idx))
            cam_cb_layout.addWidget(cam_cb)
            cam_cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cam_cb_layout.setContentsMargins(0,0,0,0)
            self.camera_table.setCellWidget(idx, 0, cam_cb_widget)
            cam_cb.stateChanged.connect(self.camStartStop)
            self.active_cams[idx]["enabled_cb"] = cam_cb

            cam_serial_widget = QTableWidgetItem(f"#{cam}")  #Used as reference for removal
            self.active_cams[idx]["table_widget"] = cam_serial_widget
            self.camera_table.setItem(idx, 1, cam_serial_widget)
            self.camera_table.setItem(idx, 2, QTableWidgetItem("Standby"))

    
    def initCam(self, idx, cam):
        cam_str = f"#{cam}"
        logging.info(f"Starting camera {cam_str}...")
        active_cam = USB_Camera(camera_index=idx, save_path="./")
        if active_cam:
            self.running_threads.watchThread(active_cam.q_thread)
            active_cam.q_thread.start()
            self.active_cams[idx].update({"cam": active_cam})
            
            #active_cam.thread.finished.connect(lambda: self.removeCam(idx))
            active_cam.finished_sig.connect(self.removeCam)
            active_cam.ready_sig.connect(self.initCamsUI)
            active_cam.status_sig.connect(self.updateCamStatus)
            active_cam.stats_sig.connect(self.updateStats)
            active_cam.update_image_sig.connect(self.updateImage)

            #self.acq_timer.timeout.connect(active_cam.getImage)
            self.save_opts.connect(active_cam.setSaveOpts)
            #self.updateSaveConfig()
            self.closing_sig.connect(active_cam.shutdown)

            start_sig = Sig("start")
            start_sig.connect(active_cam.init)
            stop_sig = Sig("stop")
            stop_sig.connect(active_cam.stop)
            shutdown_sig = Sig("shutdown")
            shutdown_sig.connect(active_cam.shutdown)

            # enable_nuc_sig = Sig("enable_nuc")
            # enable_nuc_sig.connect(active_cam.enableAutoNuc)
            # disable_nuc_sig = Sig("disable_nuc")
            # disable_nuc_sig.connect(active_cam.disableAutoNuc)
            # nuc_now_sig = Sig("nuc_now")
            # nuc_now_sig.connect(active_cam.cameraNuc)
            # high_gain_sig = Sig("high_gain")
            # high_gain_sig.connect(active_cam.switchCameraToHighGain)
            # low_gain_sig = Sig("low_gain")
            # low_gain_sig.connect(active_cam.switchCameraToLowGain)

            self.active_cams[idx].update({"start_sig": start_sig, "stop_sig": stop_sig, "shutdown_sig": shutdown_sig})
            # ,
            #                               "enable_nuc": enable_nuc_sig, "disable_nuc": disable_nuc_sig, "nuc_now": nuc_now_sig,
            #                               "high_gain": high_gain_sig, "low_gain": low_gain_sig})

            self.active_cams[idx]["start_sig"].emit(0)


    @pyqtSlot(int, bool)
    def initCamsUI(self, cam_idx, ready):
        try:
            if not ready:
                logging.info(f"Could not start {cam_idx}, removing.")
                self.removeCam(cam_idx)

            elif not "ui_ready" in self.active_cams[cam_idx]:
                try:                
                    active_cam : USB_Camera = self.active_cams[cam_idx]["cam"]
                    cam_str_ser = f"{active_cam.getTypeString()} #{active_cam.serial}"

                    cam_serial_widget = QTableWidgetItem(cam_str_ser)  #Used as reference for removal
                    self.active_cams[cam_idx]["table_widget"] = cam_serial_widget
                    self.camera_table.setItem(cam_idx, 1, cam_serial_widget)
                    self.camera_table.setItem(cam_idx, 3, QTableWidgetItem(f"{active_cam.width}x{active_cam.height}"))

                    stats_root = QTreeWidgetItem([cam_str_ser,""])
                    self.active_cams[cam_idx]["stats_root"] = stats_root
                    self.stats_tree.addTopLevelItem(stats_root)
                    stats_root.setExpanded(True)
                    stats = {x: QTreeWidgetItem(stats_root, [x, ""]) for x in ("Minimum","Maximum","Mean","Median","Frame Rate")}
                    self.active_cams[cam_idx]["stats"] = stats

                    imv = self.createImageView(active_cam.img)
                    self.active_cams[cam_idx]["imv"] = imv

                    try:
                        self.dock_cam_placeholder.close()
                    except Exception:
                        pass
                    cam_dock = Dock(cam_str_ser, size=(800,800))
                    dock_count, active_docks = self.getDockCount()
                    if dock_count == 0:
                        self.dock_area.addDock(cam_dock, 'top', self.dock_console)
                    elif dock_count == 1:
                        self.dock_area.addDock(cam_dock, 'right', self.active_cams[active_docks[-1]]['dock'])
                    elif dock_count == 2:
                        self.dock_area.addDock(cam_dock, 'bottom', self.active_cams[active_docks[-2]]['dock'])
                    elif dock_count == 3:
                        self.dock_area.addDock(cam_dock, 'bottom', self.active_cams[active_docks[-2]]['dock'])
                    #Max 4 right now
                    cam_dock.setTitle(cam_str_ser)
                    cam_dock.addWidget(self.active_cams[cam_idx]["imv"])
                    self.active_cams[cam_idx].update({"dock": cam_dock})

                    self.active_cams[cam_idx]["ui_ready"] = True

                    #active_cam.ready_sig.disconnect()   #disconnect so that UI is not re-inited if camera is restarted without full shutdown
                except Exception as e:
                    self.removeCam(cam_idx)
                    raise e
            else:
                logging.info(f"Cam {cam_idx} already exists, not re-inited.")
        except KeyError as e:
            logging.warning(f"Error with cam init: {type(e)} {str(e)}")

    @pyqtSlot()
    def camShutdownAll(self):
        for cam in self.active_cams.values():
            cam["shutdown_sig"].emit(0)   #finished signal

    @pyqtSlot()
    def camStop(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["stop_sig"].emit(0)   #stop signal
        except IndexError:
            pass
    
    @pyqtSlot()
    def camStart(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["start_sig"].emit(0)   #start signal
        except IndexError:
            pass

    def camStartStop(self, state):
        if state == QtCore.Qt.CheckState.Checked.value:
            try:
                idx = int(self.sender().text())
                cam = self.active_cams[idx]["name"]
                self.initCam(idx, cam)
            except IndexError:
                pass
        else:
            try:
                idx = int(self.sender().text())
                self.active_cams[idx]["shutdown_sig"].emit(0)   #start signal
            except IndexError:
                pass


    @pyqtSlot()
    def enableAutoNUC(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["enable_nuc"].emit(0)
        except IndexError:
            pass

    @pyqtSlot()
    def disableAutoNUC(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["disable_nuc"].emit(0)
        except IndexError:
            pass

    @pyqtSlot()
    def cameraNuc(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["nuc_now"].emit(0)
        except IndexError:
            pass

    @pyqtSlot()
    def switchCameraToHighGain(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["high_gain"].emit(0)
        except IndexError:
            pass

    @pyqtSlot()
    def switchCameraToLowGain(self):
        try:
            idx = self.getSelectedCam()
            self.active_cams[idx]["low_gain"].emit(0)
        except IndexError:
            pass

    # @pyqtSlot(QItemSelection, QItemSelection)
    # def cameraSelChanged(self, selected: QItemSelection, deselected: QItemSelection):
    #     if selected.isEmpty():
    #         self.gb_sel_cameras.setEnabled(False)
    #     else:
    #         self.gb_sel_cameras.setEnabled(True)

    def getSelectedCam(self) -> int:
        if len(self.camera_table.selectionModel().selectedRows()) > 0:
            return self.camera_table.selectionModel().selectedRows()[0].row()
        return -1

    # @pyqtSlot()
    # def acqStartStop(self):
    #     if "Start" in self.btn_acq_startstop.text():
    #         #Start Acquisition
    #         self.acq_timer.start()
    #         self.btn_acq_startstop.setText("Stop")
    #     else:
    #         #Stop Acqusition
    #         self.acq_timer.stop()
    #         self.btn_acq_startstop.setText("Start")

    # @pyqtSlot()
    # def updateSaveConfig(self):
    #     self.save_opts.emit(self.ui_datapath.text())

    # def selectDataFolder(self):
    #     folder_path = QFileDialog.getExistingDirectory(self, "Select Data Directory",
    #                                                    options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
    #     if folder_path:
    #         self.ui_datapath.setText(folder_path)
    #         logging.info(f"Updated data directory: {folder_path}")
    #         self.updateSaveConfig()
        
    @pyqtSlot(int, str)
    def updateCamStatus(self, cam_idx : int, status_str : str):
        self.camera_table.setItem(cam_idx, 2, QTableWidgetItem(status_str))

    @pyqtSlot(int, dict)
    def updateStats(self, cam_idx : int, stats : dict):
        for k, x in stats.items():
            try:
                i : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k] 
            except KeyError:
                self.active_cams[cam_idx]["stats"][k] = QTreeWidgetItem(self.active_cams[cam_idx]["stats_root"])
                i : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k] 
            i.setText(1, f"{x:.2f}")

    def updateImage(self, cam_idx : int):
        imv :pg.ImageView = self.active_cams[cam_idx]["imv"]
        imv.updateImage()
        imv.setImage(imv.image, autoHistogramRange=self.cb_auto_hist.isChecked(), autoLevels=self.cb_auto_levels.isChecked(), autoRange=self.cb_auto_range.isChecked(), levelMode='mono')

    @pyqtSlot(int)
    def removeCam(self, idx):
        logging.debug(f"Removing cam {idx}")
        try:
            # try:
            #     table_row = self.camera_table.row(self.active_cams[idx]["table_widget"])
            #     self.camera_table.removeRow(table_row)
            # except KeyError:
            #     pass
            try:
                cb : QCheckBox = self.active_cams[idx]["enabled_cb"]
                with SBlock(cb) as cb_blocked:
                    cb_blocked.setChecked(False)
            except KeyError:
                pass
            try:
                self.stats_tree.takeTopLevelItem(self.stats_tree.indexOfTopLevelItem(self.active_cams[idx]["stats_root"]))
            except KeyError:
                pass
            try:
                self.active_cams[idx]["dock"].close()
                del self.active_cams[idx]["dock"]
            except KeyError:
                pass
            try:
                del self.active_cams[idx]["ui_ready"]
            except KeyError:
                pass

            if self.getDockCount()[0] == 0:
                self.dock_area.addDock(self.dock_cam_placeholder, 'top', self.dock_console)
        except Exception as e:
            logging.warning(f"Error removing cam {idx}: {str(e)}")

    def getDockCount(self):
        docks = ["dock" in x for x in self.active_cams.values()]
        dock_count = sum(docks)
        active_docks = [i for i,d in enumerate(docks) if d]
        return dock_count, active_docks

    def closeEvent(self, a0):
        event = a0
        if self.ready_to_close:
            event.accept()
        elif self.closing:
            event.ignore()
        else:
            #self.acq_timer.stop()
            #self.btn_acq_startstop.setText("Start")
            self.closing_sig.emit()
            self.closing = True
            if self.ready_to_close:
                self.closeEvent(event)      #to catch when "finished" and "quit" execute before event is ignored
            else:
                event.ignore()

    @pyqtSlot()
    def finished(self):
        logging.info("Shutting down...")

        if len(self.running_threads) == 0:
            self.quit()
        else:
            logging.debug("Stopping %i thread(s)" % len(self.running_threads))
            sys.stdout.flush()
            self._i = 0
            
            self.running_threads.allDone.connect(self.quit)
            self.running_threads.countChange.connect(self.check_threads)
    
            self.shut_timer = QtCore.QTimer(self)
            self.shut_timer.timeout.connect(self.check_shutdown)
            self.shut_timer.start(1000)

    @pyqtSlot(int)
    def check_threads(self, n):
        logging.debug("Waiting for %i thread(s)" % n)

    @pyqtSlot()
    def check_shutdown(self):
        self._i += 1
        
        if self._i > 5 or self.running_threads.active_threads == 0:
            logging.warning("Thread(s) blocked, attempting to force quit application.")
            self.quit()
            
        elif self._i == 10:   #10 second timeout for stopping all threads
            self._i += 1
            bad_threads = []
            for i in self.running_threads.active_threads:
                bad_threads.append(i.objectName())
            logging.warning("%s thread(s) unresponsive. Force terminating." % bad_threads)
            
            for i in self.running_threads.active_threads:
                i.terminate()
            
    def quit(self):
        logging.info("Done.")
        try:
            self.shut_timer.stop()
        except AttributeError:
            pass
        self.ready_to_close = True
        self.close()


if __name__ == '__main__':
    warnings.filterwarnings("ignore", message=".*sipPyTypeDict\\(\\) is deprecated.*")
    logging.basicConfig(level=logging.INFO, format='[%(levelname)-10s] (%(threadName)-10s), %(asctime)s, %(message)s')

    app = QApplication([])
    viewer = Viewer()
    viewer.show()

    sys.exit(app.exec())


