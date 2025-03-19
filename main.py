import sys
import logging
import argparse
import warnings

import threading

from PyQt6 import QtCore
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot, QObject, QSize, QItemSelection

import numpy as np
from scipy import stats

import pyqtgraph as pg
from pyqtgraph.dockarea import Dock, DockArea

from camera import USB_Camera, Camera_Search
from util import *

class Crosshair(pg.GraphicsObject):
    def __init__(self, image_view: pg.ImageView):
        super().__init__()
        self.image_view = image_view
        self.img_shape = self.image_view.getImageItem().image.shape
        self.origin = (self.img_shape[0]/2, self.img_shape[1]/2)
        pen_dashed_white = pg.mkPen(color='w', width=2, style=Qt.PenStyle.DashLine)

        # Global crosshair
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pen_dashed_white)
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pen_dashed_white)
        self.image_view.addItem(self.vLine, ignoreBounds=True)
        self.image_view.addItem(self.hLine, ignoreBounds=True)
        self.vLine.setPos(self.origin[0])
        self.hLine.setPos(self.origin[1])

        self.pen_dot_blue = pg.mkPen(color='b', width=2, style=Qt.PenStyle.DotLine)
        self.pen_dot_green = pg.mkPen(color='g', width=2, style=Qt.PenStyle.DotLine)
        self.pen_dash_lightgray = pg.mkPen(color='lightgray', width=1, style=Qt.PenStyle.DashLine)
        self.pen_solid_blue = pg.mkPen(color='blue', width=1, style=Qt.PenStyle.SolidLine)
        self.pen_solid_red = pg.mkPen(color='red', width=1, style=Qt.PenStyle.SolidLine)
        self.pen_solid_green = pg.mkPen(color='green', width=1, style=Qt.PenStyle.SolidLine)

        self.roi = pg.CrosshairROI(movable=True, rotatable=True, resizable=True)
        self.roi.setPen()
        for h in self.roi.getHandles():
            self.roi.removeHandle(h)
        self.roi.setVisible(False)
        self.target_center = self.roi.pos()
        self.target_size = self.roi.size()
        self.image_view.addItem(self.roi)

        self.vert_plot = pg.PlotWidget(image_view.parentWidget(), labels={'right': 'Y-Axis Crossection Intensity'}, pen='b')
        self.vert_plot.hideAxis('bottom')
        self.vert_plot.hideAxis('left')
        self.vert_plot.showGrid(True, True)
        self.vert_plot.setFixedWidth(200)
        self.vert_plot_gauss = self.vert_plot.plot(pen=self.pen_dash_lightgray, name='Gaussian Curve')
        self.vert_plot_image = self.vert_plot.plot(pen=self.pen_solid_blue, name='Image Data')

        self.hor_plot = pg.PlotWidget(image_view.parentWidget(), labels={'bottom': 'X-Axis Crossection Intensity'}, pen='b')
        self.hor_plot.hideAxis('left')
        self.hor_plot.showGrid(True, True)
        self.hor_plot.setFixedHeight(200)
        self.hor_plot_gauss = self.hor_plot.plot(pen=self.pen_dash_lightgray, name='Gaussian Curve')
        self.hor_plot_image = self.hor_plot.plot(pen=self.pen_solid_blue, name='Image Data')

        self.circ_widg = pg.GraphicsLayoutWidget(image_view.parentWidget())
        self.circ_widg.setFixedSize(200,200)
        self.circ_plot = self.circ_widg.addPlot()

        self.circ_ellipse = pg.QtWidgets.QGraphicsEllipseItem(-0.5, -0.5, 1, 1)
        self.circ_ellipse.setPen(self.pen_dash_lightgray)
        self.circ_plot.addItem(self.circ_ellipse)
        self.circ_image = pg.QtWidgets.QGraphicsEllipseItem(-0.5, -0.5, 1, 1)
        self.circ_image.setPen(self.pen_solid_red)
        self.circ_plot.addItem(self.circ_image)
        
        self.circ_plot.setXRange(-0.6, 0.6, padding=0)
        self.circ_plot.setYRange(-0.6, 0.6, padding=0)
        self.circ_plot.setAspectLocked(True)
        self.circ_plot.showGrid(True)
        self.circ_plot.hideAxis('bottom')
        self.circ_plot.hideAxis('left')

        self.updatePlots(reset=True)

    def updatePlots(self, reset=False):
        try:
            assert reset == False
            roi_size = self.roi.size()
            self.target_center = self.roi.pos()
            
            y_range_vert = (int(max(self.target_center[1] - 0.5 * roi_size[1], 0)), int(min(self.target_center[1] + 0.5 * roi_size[1], self.img_shape[1])))
            y_values_vert = np.array(range(*y_range_vert))
            vert_mu = self.target_center[1]
            vert_sigma = roi_size[1] / 6

            x_range_hor = (int(max(self.target_center[0] - 0.5 * roi_size[0], 0)), int(min(self.target_center[0] + 0.5 * roi_size[0], self.img_shape[0])))
            x_values_hor = np.array(range(*x_range_hor))
            hor_mu = self.target_center[0]
            hor_sigma = roi_size[0] / 6

            vert_image_curve = self.image_view.image[int(hor_mu), y_range_vert[0]:y_range_vert[1]]
            vert_gauss = stats.norm(vert_mu, vert_sigma).pdf(y_values_vert)
            vert_gaussian_curve = vert_image_curve.min() + ((vert_gauss / np.max(vert_gauss)) * vert_image_curve.max())
            x_range_vert = (vert_image_curve.min(), vert_image_curve.max())
        
            hor_image_curve = self.image_view.image[x_range_hor[0]:x_range_hor[1], int(vert_mu)]
            hor_gauss = stats.norm(hor_mu, hor_sigma).pdf(x_values_hor)
            hor_gaussian_curve = hor_image_curve.min() + ((hor_gauss / np.max(hor_gauss)) * hor_image_curve.max())
            y_range_hor = (hor_image_curve.max(), hor_image_curve.min())

            # Show image data plots
            self.hor_plot_image.setVisible(True)
            self.vert_plot_image.setVisible(True)
            self.circ_image.setVisible(True)
        except (ValueError, AssertionError):
            x_range_vert = (0, 128)
            y_range_vert = (-3, 3)
            x_range_hor = (-3, 3)
            y_range_hor = (0, 128)
            vert_mu = 0      # Mean of the distribution
            vert_sigma = 1   # Standard deviation
            hor_mu = 0
            hor_sigma = 1

            y_values_vert = np.linspace(vert_mu - 3 * vert_sigma, vert_mu + 3 * vert_sigma, 100)
            vert_gaussian_curve = stats.norm(vert_mu, vert_sigma).pdf(y_values_vert) * 255
            vert_image_curve = np.empty((100))
        
            x_values_hor = np.linspace(hor_mu - 3 * hor_sigma, hor_mu + 3 * hor_sigma, 100)
            hor_gaussian_curve = stats.norm(hor_mu, hor_sigma).pdf(x_values_hor) * 255
            hor_image_curve = np.empty((100))

            # Hide image data plots
            self.hor_plot_image.setVisible(False)
            self.vert_plot_image.setVisible(False)
            self.circ_image.setVisible(False)
            
        #Update plot ranges
        self.vert_plot.enableAutoRange(axis='x')
        self.vert_plot.setAutoVisible(x=True)
        #self.vert_plot.setXRange(x_range_vert[0], x_range_vert[1])
        self.vert_plot.setYRange(y_range_vert[0], y_range_vert[1])

        self.hor_plot.enableAutoRange(axis='y')
        self.hor_plot.setAutoVisible(y=True)
        self.hor_plot.setXRange(x_range_hor[0], x_range_hor[1])
        #self.hor_plot.setYRange(y_range_hor[0], y_range_hor[1])
        
        #Update curves
        self.hor_plot_gauss.setData(x_values_hor, hor_gaussian_curve)
        self.hor_plot_image.setData(x_values_hor, hor_image_curve)

        self.vert_plot_gauss.setData(vert_gaussian_curve, y_values_vert)
        self.vert_plot_image.setData(vert_image_curve, y_values_vert)

        sigma_ratio = vert_sigma / hor_sigma
        if 0.95 < sigma_ratio < 1.05:
            self.circ_image.setPen(self.pen_solid_green)
        else:
            self.circ_image.setPen(self.pen_solid_red)
        self.circ_image.setRect(-(1/sigma_ratio)/2, -sigma_ratio/2, 1/sigma_ratio, sigma_ratio)

    def setTarget(self, pos, widths):
        if 0 <= pos[0] < self.img_shape[0] and 0 <= pos[1] < self.img_shape[1]:
            if (self.origin[0] - 5 < pos[0] < self.origin[0] + 5) and (self.origin[1] - 5 < pos[1] < self.origin[1] + 5):
                self.roi.setPen(self.pen_dot_green)
            else:
                self.roi.setPen(self.pen_dot_blue)

            self.roi.setSize(widths, center=(0.5, 0.5), update=False)
            self.roi.setPos(pos)
            self.roi.setVisible(True)
            self.updatePlots(reset=False)
        else:
            self.clearTarget()

    def clearTarget(self):
        self.roi.setVisible(False)
        self.updatePlots(reset=True)



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

        parser = argparse.ArgumentParser(description="Utility for acquiring images from a USB camera for laser alignment.")      
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

        #Callbacks
        self.btn_search_for_cams.clicked.connect(self.searchForCams)
        self.btn_shutdown_all.clicked.connect(self.camShutdownAll)
        #Finally, init cams
        self.searchForCams()

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
        self.cb_auto_range.setChecked(False)
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

            self.save_opts.connect(active_cam.setSaveOpts)
            self.closing_sig.connect(active_cam.shutdown)

            start_sig = Sig("start")
            start_sig.connect(active_cam.init)
            stop_sig = Sig("stop")
            stop_sig.connect(active_cam.stop)
            shutdown_sig = Sig("shutdown")
            shutdown_sig.connect(active_cam.shutdown)

            self.active_cams[idx].update({"start_sig": start_sig, "stop_sig": stop_sig, "shutdown_sig": shutdown_sig})
            self.active_cams[idx]["start_sig"].emit(0)

    def createImageView(self, img):
        imv = pg.ImageView()
        imv.setPredefinedGradient('turbo') #'CET-R4')
        imv.setImage(img)
        return imv
    
    def createWidget(self, imv: pg.ImageView, crosshair: Crosshair):
        widget = QWidget()
        layout = QGridLayout()
        layout.addWidget(imv, 0, 0)
        layout.addWidget(crosshair.vert_plot, 0, 1)
        layout.addWidget(crosshair.hor_plot, 1, 0)
        layout.addWidget(crosshair.circ_widg, 1, 1)

        widget.setLayout(layout)
        return widget

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
                    #stats = {x: QTreeWidgetItem(stats_root, [x, ""]) for x in ("Minimum","Maximum","Mean","Median","Frame Rate")}
                    #Create dynamically instead in updateStats
                    self.active_cams[cam_idx]["stats"] = {}

                    imv = self.createImageView(active_cam.img)
                    crosshair = Crosshair(imv)
                    widget = self.createWidget(imv, crosshair)
                    self.active_cams[cam_idx]["imv"] = imv
                    self.active_cams[cam_idx]["crosshair"] = crosshair
                    self.active_cams[cam_idx]["widget"] = widget

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
                    cam_dock.addWidget(self.active_cams[cam_idx]["widget"])
                    self.active_cams[cam_idx].update({"dock": cam_dock})

                    self.active_cams[cam_idx]["ui_ready"] = True

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


    def getSelectedCam(self) -> int:
        if len(self.camera_table.selectionModel().selectedRows()) > 0:
            return self.camera_table.selectionModel().selectedRows()[0].row()
        return -1
        
    @pyqtSlot(int, str)
    def updateCamStatus(self, cam_idx : int, status_str : str):
        self.camera_table.setItem(cam_idx, 2, QTableWidgetItem(status_str))

    @pyqtSlot(int, dict)
    def updateStats(self, cam_idx : int, stats : dict):
        for k, x in stats.items():
            try:
                i : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k] 
            except KeyError:
                self.active_cams[cam_idx]["stats"][k] = QTreeWidgetItem(self.active_cams[cam_idx]["stats_root"], [k, ""])
                i : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k]
            if type(x) is dict:
                for k_x, y in x.items():
                    try:
                        j : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k + "_" + k_x]
                    except KeyError:
                        self.active_cams[cam_idx]["stats"][k + "_" + k_x] = QTreeWidgetItem(i, [k_x, ""])
                        j : QTreeWidgetItem = self.active_cams[cam_idx]["stats"][k + "_" + k_x]
                        i.setExpanded(True)         
                    if type(y) is str:
                        j.setText(1, y)
                    else:
                        j.setText(1, f"{y:.2f}")
            else:     
                if type(x) is str:
                    i.setText(1, x)
                else:
                    i.setText(1, f"{x:.2f}")

        crosshair: Crosshair = self.active_cams[cam_idx]["crosshair"]
        try:
            target_x = stats["Gaussian"]["Center X"]
            target_y = stats["Gaussian"]["Center Y"]
            width_x = stats["Gaussian"]["Sigma X"] * 6
            width_y = stats["Gaussian"]["Sigma Y"] * 6
            crosshair.setTarget((target_x, target_y), (width_x, width_y))
        except (KeyError, TypeError):
            crosshair.clearTarget()

    def updateImage(self, cam_idx : int):
        try:
            imv: pg.ImageView = self.active_cams[cam_idx]["imv"]
            imv.setImage(imv.image, autoHistogramRange=self.cb_auto_hist.isChecked(), autoLevels=self.cb_auto_levels.isChecked(), autoRange=self.cb_auto_range.isChecked(), levelMode='mono')
        except KeyError:
            pass

    @pyqtSlot(int)
    def removeCam(self, idx):
        logging.debug(f"Removing cam {idx}")
        try:
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


