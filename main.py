import sys
import logging
import argparse
import warnings

from PyQt6 import QtCore
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot, QObject, QSize, QItemSelection

from pyqtgraph.dockarea import Dock, DockArea

from camera import USB_Camera, Camera_Search
from util import *


class Viewer(QMainWindow):
    save_opts = pyqtSignal(str, bool,bool,bool,float,float)
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
        parser.add_argument("-i", "--interval", type=float, default=1.0, help="Acquisition interval")
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
        self.acq_timer = QTimer()
        self.acq_timer.setInterval(int(self.ui_interval.value() * 1000))
        self.acq_timer.timeout.connect(QApplication.processEvents)
        self.ui_interval.valueChanged.connect(lambda new_val : self.acq_timer.setInterval(int(new_val * 1000)))

        #Callbacks
        self.btn_search_for_cams.clicked.connect(self.searchForCams)
        self.btn_shutdown_all.clicked.connect(self.camShutdownAll)
        self.btn_start_selected.clicked.connect(self.camStart)
        self.btn_stop_selected.clicked.connect(self.camStop)

        self.btn_acq_startstop.clicked.connect(self.acqStartStop)
        self.cb_save_binary.clicked.connect(self.updateSaveConfig)
        self.cb_save_jpg.clicked.connect(self.updateSaveConfig)
        self.cb_save_tiff.clicked.connect(self.updateSaveConfig)
        self.btn_browse.clicked.connect(self.selectDataFolder)

        #Finally, init cams
        self.searchForCams()

        #Auto-start from command line (Note, this may occur before cams are found. This is ok, they will begin when inited.)
        if self.args.start:
            self.acqStartStop()

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
        self.camera_table.setFixedSize(251,100)
        self.camera_table.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.camera_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.camera_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.camera_table.setColumnCount(4)
        self.camera_table.horizontalHeader().setDefaultSectionSize(50)
        self.camera_table.horizontalHeader().setStretchLastSection(True)
        self.camera_table.selectionModel().selectionChanged.connect(self.cameraSelChanged)

        item0 = QTableWidgetItem()
        item0.setText("Type") 
        self.camera_table.setHorizontalHeaderItem(0, item0)
        self.camera_table.setColumnWidth(0, 65)

        item1 = QTableWidgetItem()
        item1.setText("Serial #") 
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

        #Selected Camera Buttons
        self.gb_sel_cameras = QGroupBox(self.config_widget)
        self.gb_sel_cameras.setObjectName(u"gb_sel_cameras")
        self.gb_sel_cameras.setTitle("Selected Camera")
        self.gb_sel_cameras.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.gb_sel_cameras.setEnabled(False)

        self.sel_camera_btn_layout = QGridLayout(self.gb_sel_cameras)

        self.btn_stop_selected = QPushButton(self.gb_sel_cameras)
        self.btn_stop_selected.setObjectName(u"btn_stop_selected")
        self.btn_stop_selected.setText("Stop Selected")
        self.btn_stop_selected.setFixedSize(QSize(111,24))
        self.sel_camera_btn_layout.addWidget(self.btn_stop_selected, 1, 1, Qt.AlignmentFlag.AlignCenter)

        self.btn_start_selected = QPushButton(self.gb_sel_cameras)
        self.btn_start_selected.setObjectName(u"btn_start_selected")
        self.btn_start_selected.setText("Start Selected")
        self.btn_start_selected.setFixedSize(QSize(111,24))
        self.sel_camera_btn_layout.addWidget(self.btn_start_selected, 1, 0, Qt.AlignmentFlag.AlignCenter)

        self.cb_enable_nuc = QCheckBox(self.gb_sel_cameras)
        self.cb_enable_nuc.setObjectName(u"cb_enable_nuc")
        self.cb_enable_nuc.setText("Enable Auto-NUC")
        self.cb_enable_nuc.setChecked(True)
        self.sel_camera_btn_layout.addWidget(self.cb_enable_nuc, 2, 0, Qt.AlignmentFlag.AlignCenter)

        self.btn_nuc = QPushButton(self.gb_sel_cameras)
        self.btn_nuc.setObjectName(u"btn_nuc")
        self.btn_nuc.setText("Run NUC Now")
        self.btn_nuc.setFixedSize(QSize(111,24))
        self.sel_camera_btn_layout.addWidget(self.btn_nuc, 3, 0, Qt.AlignmentFlag.AlignCenter)

        self.rb_high_gain = QRadioButton("High Gain")
        self.rb_high_gain.setObjectName(u"rb_high_gain")
        self.rb_high_gain.setChecked(False)
        self.sel_camera_btn_layout.addWidget(self.rb_high_gain, 2, 1, Qt.AlignmentFlag.AlignCenter)

        self.rb_low_gain = QRadioButton("Low Gain")
        self.rb_low_gain.setObjectName(u"rb_low_gain")
        self.rb_low_gain.setChecked(True)
        self.sel_camera_btn_layout.addWidget(self.rb_low_gain, 3, 1, Qt.AlignmentFlag.AlignCenter)

        self.rbg_gain = QButtonGroup()
        self.sel_camera_btn_layout.addWidget(self.rb_low_gain, 3, 1, Qt.AlignmentFlag.AlignCenter)
        self.rbg_gain = QButtonGroup()
        self.rbg_gain.addButton(self.rb_high_gain)
        self.rbg_gain.addButton(self.rb_low_gain)

        self.verticalLayout.addWidget(self.gb_sel_cameras)

        #Acqusition
        self.groupBox_acquisition = QGroupBox(self.config_widget)
        self.groupBox_acquisition.setObjectName(u"groupBox_acquisition")
        self.groupBox_acquisition.setTitle("Acquisition")
        self.groupBox_acquisition.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.acq_layout = QGridLayout(self.groupBox_acquisition)
        self.acq_layout.setObjectName(u"acq_layout")

        self.btn_acq_startstop = QPushButton(self.groupBox_acquisition)
        self.btn_acq_startstop.setObjectName(u"btn_acq_startstop")
        self.btn_acq_startstop.setText("Start")
        self.acq_layout.addWidget(self.btn_acq_startstop, 0, 0, Qt.AlignmentFlag.AlignLeft)

        self.label_interval = QLabel(self.groupBox_acquisition)
        self.label_interval.setObjectName(u"label_interval")
        self.label_interval.setText("Interval (s):") 
        self.acq_layout.addWidget(self.label_interval, 0, 1, Qt.AlignmentFlag.AlignRight)

        self.ui_interval = QDoubleSpinBox(self.groupBox_acquisition)
        self.ui_interval.setObjectName(u"ui_interval")
        self.ui_interval.setValue(self.args.interval)
        self.acq_layout.addWidget(self.ui_interval, 0, 2, Qt.AlignmentFlag.AlignLeft)

        #Save Options
        self.cb_save_binary = QCheckBox(self.groupBox_acquisition)
        self.cb_save_binary.setObjectName(u"cb_save_binary")
        self.cb_save_binary.setText("Save Binary") 
        self.cb_save_binary.setChecked(self.args.binary)
        self.cb_save_jpg = QCheckBox(self.groupBox_acquisition)
        self.cb_save_jpg.setObjectName(u"cb_save_jpg")
        self.cb_save_jpg.setText("Save JPG")
        self.cb_save_jpg.setChecked(self.args.jpg)
        self.cb_save_tiff = QCheckBox(self.groupBox_acquisition)
        self.cb_save_tiff.setObjectName(u"cb_save_tiff")
        self.cb_save_tiff.setText("Save TIFF")
        self.cb_save_tiff.setChecked(self.args.tiff)

        self.save_cb_layout = QVBoxLayout()
        self.save_cb_layout.addWidget(self.cb_save_binary)
        self.save_cb_layout.addWidget(self.cb_save_jpg)
        self.save_cb_layout.addWidget(self.cb_save_tiff)
        self.acq_layout.addLayout(self.save_cb_layout, 1, 0, Qt.AlignmentFlag.AlignLeft)

        #JPG Scale
        self.groupBox_jpg_scale = QGroupBox(self.groupBox_acquisition)
        self.groupBox_jpg_scale.setObjectName(u"groupBox_jpg_scale")
        self.groupBox_jpg_scale.setTitle("JPG Scale (°C)") 

        self.save_opts_gb_layout = QGridLayout(self.groupBox_jpg_scale)
        self.save_opts_gb_layout.setObjectName(u"save_opts_gb_layout")

        self.ui_jpg_min = QDoubleSpinBox(self.groupBox_jpg_scale)
        self.ui_jpg_min.setObjectName(u"ui_jpg_min")
        self.ui_jpg_min.setValue(self.args.min_value)
        self.save_opts_gb_layout.addWidget(self.ui_jpg_min, 0, 1)

        self.label_jpg_min = QLabel(self.groupBox_jpg_scale)
        self.label_jpg_min.setObjectName(u"label_jpg_min")
        self.label_jpg_min.setText("Min:") 
        self.save_opts_gb_layout.addWidget(self.label_jpg_min, 0,0)

        self.ui_jpg_max = QDoubleSpinBox(self.groupBox_jpg_scale)
        self.ui_jpg_max.setObjectName(u"ui_jpg_max")
        self.ui_jpg_max.setValue(self.args.max_value)
        self.save_opts_gb_layout.addWidget(self.ui_jpg_max, 1, 1)

        self.label_jpg_max = QLabel(self.groupBox_jpg_scale)
        self.label_jpg_max.setObjectName(u"label_jpg_max")
        self.label_jpg_max.setText("Max:") 
        self.save_opts_gb_layout.addWidget(self.label_jpg_max, 1, 0)

        self.acq_layout.addWidget(self.groupBox_jpg_scale, 1, 1, 1, 2, Qt.AlignmentFlag.AlignCenter)

        #Data Path
        self.ui_datapath = QLineEdit(self.groupBox_acquisition)
        self.ui_datapath.setObjectName(u"ui_datapath")
        self.ui_datapath.setText(self.args.output_path)
        self.acq_layout.addWidget(self.ui_datapath)

        self.label_datapath = QLabel(self.groupBox_acquisition)
        self.label_datapath.setObjectName(u"label_datapath")
        self.label_datapath.setText("Data Path:") 
        self.acq_layout.addWidget(self.label_datapath)

        self.btn_browse = QPushButton(self.groupBox_acquisition)
        self.btn_browse.setObjectName(u"btn_browse")
        self.btn_browse.setText("Browse") 
        self.acq_layout.addWidget(self.btn_browse)

        self.verticalLayout.addWidget(self.groupBox_acquisition)

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

    @pyqtSlot(list)
    def initCams(self, cam_list):
        cam_types = {-1:"Unknown", 0:"9000 Series", 1:"8000 Series", 2:"SWIR Series"}
        self.searching = False
        for idx, cam in enumerate(cam_list):
            cam_str = f"#{cam}"
            logging.info(f"Starting camera {cam_str}...")
            active_cam = USB_Camera(camera_index=cam, save_path=self.ui_datapath.text())

            if active_cam:
                self.running_threads.watchThread(active_cam.q_thread)
                self.active_cams[idx] = {"cam": active_cam}

                #active_cam.thread.finished.connect(lambda: self.removeCam(idx))
                active_cam.finished_sig.connect(self.removeCam)
                active_cam.ready_sig.connect(self.initCamsUI)
                active_cam.status_sig.connect(self.updateCamStatus)
                active_cam.stats_sig.connect(self.updateStats)

                self.acq_timer.timeout.connect(active_cam.getImage)
                self.save_opts.connect(active_cam.setSaveOpts)
                self.updateSaveConfig()
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

                #Update UI
                if self.camera_table.rowCount() < len(self.active_cams) + 1:
                    self.camera_table.insertRow(idx)
                self.camera_table.setItem(idx, 0, QTableWidgetItem(f"{cam}"))
                self.camera_table.setItem(idx, 1, QTableWidgetItem(f"#{cam}"))
                self.camera_table.setItem(idx, 2, QTableWidgetItem("Starting"))

                try:
                    self.dock_cam_placeholder.close()
                except Exception:
                    pass
                cam_dock = Dock(cam_str, size=(800,800))
                if idx == 0:
                    self.dock_area.addDock(cam_dock, 'top', self.dock_console)
                elif idx == 1:
                    self.dock_area.addDock(cam_dock, 'right', self.active_cams[0]["dock"])
                elif idx == 2:
                    self.dock_area.addDock(cam_dock, 'bottom', self.active_cams[0]["dock"])
                elif idx == 3:
                    self.dock_area.addDock(cam_dock, 'bottom', self.active_cams[1]["dock"])
                #Max 4 right now
                self.active_cams[idx].update({"dock": cam_dock})

                active_cam.q_thread.start()

    @pyqtSlot(int)
    def initCamsUI(self, cam_idx):
        try:
            if not "ui_ready" in self.active_cams[cam_idx]:
                try:                
                    active_cam : USB_Camera = self.active_cams[cam_idx]["cam"]
                    cam_str_ser = f"{active_cam.getTypeString()} #{active_cam.serial}"

                    self.camera_table.setItem(cam_idx, 0, QTableWidgetItem(active_cam.getTypeString()))
                    cam_serial_widget = QTableWidgetItem(str(active_cam.serial))  #Used as reference for removal
                    self.camera_table.setItem(cam_idx, 1, cam_serial_widget)
                    self.camera_table.setItem(cam_idx, 3, QTableWidgetItem(f"{active_cam.width}x{active_cam.height}"))
                    self.active_cams[cam_idx].update({"table_widget": cam_serial_widget})

                    stats_root = QTreeWidgetItem([cam_str_ser,""])
                    self.active_cams[cam_idx]["stats_root"] = stats_root
                    self.stats_tree.addTopLevelItem(stats_root)
                    stats_root.setExpanded(True)
                    stats = {x: QTreeWidgetItem(stats_root, [x, ""]) for x in ("Minimum","Maximum","Mean","Median","Frame Rate")}
                    self.active_cams[cam_idx]["stats"] = stats

                    cam_dock = self.active_cams[cam_idx]["dock"]
                    cam_dock.setTitle(cam_str_ser)
                    cam_dock.addWidget(active_cam.imv)

                    self.active_cams[cam_idx]["ui_ready"] = True

                    #active_cam.ready_sig.disconnect()   #disconnect so that UI is not re-inited if camera is restarted without full shutdown
                except Exception as e:
                    self.removeCam(cam_idx)
                    raise e
            else:
                logging.info(f"Cam {cam_idx} already exists, not re-inited.")
        except KeyError as e:
            logging.warning(f"Error with cam init: {str(e)}")

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

    @pyqtSlot(QItemSelection, QItemSelection)
    def cameraSelChanged(self, selected: QItemSelection, deselected: QItemSelection):
        if selected.isEmpty():
            self.gb_sel_cameras.setEnabled(False)
        else:
            self.gb_sel_cameras.setEnabled(True)

    def getSelectedCam(self) -> int:
        if len(self.camera_table.selectionModel().selectedRows()) > 0:
            return self.camera_table.selectionModel().selectedRows()[0].row()
        return -1

    @pyqtSlot()
    def acqStartStop(self):
        if "Start" in self.btn_acq_startstop.text():
            #Start Acquisition
            self.acq_timer.start()
            self.btn_acq_startstop.setText("Stop")
        else:
            #Stop Acqusition
            self.acq_timer.stop()
            self.btn_acq_startstop.setText("Start")

    @pyqtSlot()
    def updateSaveConfig(self):
        opts = (self.ui_datapath.text(),
                self.cb_save_binary.isChecked(),
                self.cb_save_jpg.isChecked(),
                self.cb_save_tiff.isChecked(),
                self.ui_jpg_min.value(),
                self.ui_jpg_max.value())
        self.save_opts.emit(*opts)

    def selectDataFolder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Data Directory",
                                                       options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        if folder_path:
            self.ui_datapath.setText(folder_path)
            logging.info(f"Updated data directory: {folder_path}")
            self.updateSaveConfig()
        
    @pyqtSlot(int, str)
    def updateCamStatus(self, cam_idx : int, status_str : str):
        self.camera_table.setItem(cam_idx, 2, QTableWidgetItem(status_str))

    @pyqtSlot(int, dict)
    def updateStats(self, cam_idx : int, stats : dict):
        for k, x in stats.items():
            i : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k] 
            i.setText(1, f"{x:.2f}")

    @pyqtSlot(int)
    def removeCam(self, idx):
        logging.debug(f"Removing cam {idx}")
        try:
            table_row = self.camera_table.row(self.active_cams[idx]["table_widget"])
            self.camera_table.removeRow(table_row)

            self.stats_tree.takeTopLevelItem(self.stats_tree.indexOfTopLevelItem(self.active_cams[idx]["stats_root"]))
            
            self.active_cams[idx]["dock"].close()
            self.active_cams.pop(idx)
            if len(self.active_cams) == 0:
                self.dock_area.addDock(self.dock_cam_placeholder, 'top', self.dock_console)
        except Exception as e:
            logging.warning(f"Error removing cam {idx}: {str(e)}")

    def closeEvent(self, a0):
        event = a0
        if self.ready_to_close:
            event.accept()
        elif self.closing:
            event.ignore()
        else:
            self.acq_timer.stop()
            self.btn_acq_startstop.setText("Start")
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


