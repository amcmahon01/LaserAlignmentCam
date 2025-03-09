import logging
import threading
from os import path, makedirs
from datetime import datetime
from time import sleep, time
from ctypes import sizeof, c_float

import numpy as np
import cv2

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, QThread
import pyqtgraph as pg


class Camera_Search(QObject):
    result = pyqtSignal(list)

    def __init__(self, skip_idxs=[]):
        QObject.__init__(self)

        self.skip_idxs = skip_idxs

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_Search")
        self.moveToThread(self.q_thread)
        self.q_thread.started.connect(self.findCameras)
    
    def findCameras(self):
        #https://stackoverflow.com/a/61768256
        # checks the first 10 indexes.
        index = 0
        arr = []
        i = 10
        while i > 0:
            cap = cv2.VideoCapture(index)
            if cap.read()[0]:
                arr.append(index)
                cap.release()
            index += 1
            i -= 1
        self.result.emit(arr)
        self.q_thread.quit()


class USB_Camera(QObject):
    ready_sig = pyqtSignal(int)
    status_sig = pyqtSignal(int, str)
    stats_sig = pyqtSignal(int, dict)
    finished_sig = pyqtSignal(int)

    def __init__(self, camera_index:int, save_images=True, save_path="."):
        QObject.__init__(self)
        self.camera_index = camera_index
        self.camera_type = ""
        self.active = False
        self.acquiring = False
        self.last_frame_time = time()

        self.serial = "N/A"
        self.save_images = save_images
        self.save_path = save_path
        self.save_png = False
        self.jpg_min = 0
        self.jpg_max = 45
        self.frame_rate = 0
        
        self.stats = {}

        self.imv = pg.ImageView()
        self.imv.setPredefinedGradient('turbo') #'CET-R4')

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_{camera_index}")
        self.moveToThread(self.q_thread)
        self.q_thread.started.connect(self.init)

    @pyqtSlot()
    def init(self):
        threading.current_thread().name = QThread.currentThread().objectName()  #fix names
        self.status_sig.emit(self.camera_index, "Starting")

        self.cam = cv2.VideoCapture()
        self.cam.setExceptionMode(True)

        try:
            self.cam.open(self.camera_index)

            self.width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            #self.serial = self.getCameraSerialNumber()

            ret, frame = self.cam.read()
            if ret:
                self.imv.setImage(frame, autoHistogramRange=True, autoLevels=True, autoRange=True, levelMode='mono')
            else:
                raise Exception(f"Could not capture frame")

            #Insane initialization to get autoLevels
            # self.imv.setImage(self.img_data, autoHistogramRange=True, autoLevels=True, levelMode='mono')
            # temperature_image = self.getTemperatureImage()
            # img = np.reshape(temperature_image.cast('f'), (self.height, self.width))
            # np.copyto(self.img_data, img.T)
            # self.imv.getHistogramWidget().imageChanged(autoLevel=True)
            # self.imv.normRadioChanged()
                        
            logging.info(f"Started camera {self.camera_index}.")
            self.active = True
            self.ready_sig.emit(self.camera_index)
            self.status_sig.emit(self.camera_index, "Ready")
            return True
        except Exception as e:
            logging.error(f"Error starting camera {self.camera_index}: {type(e)} {e}")
            try:
                self.cam.release()
            except Exception:
                pass
            return False

    @pyqtSlot()    
    def stop(self):
        self.status_sig.emit(self.camera_index, "Stopping")
        self.cam.release()
        logging.info(f"Stopped camera {self.camera_index}.")
        self.active = False
        self.width = 0
        self.height = 0
        self.serial = ""
        self.status_sig.emit(self.camera_index, "Stopped")

    @pyqtSlot()
    def shutdown(self):
        if self.active:
            self.stop()
        self.status_sig.emit(self.camera_index, "Shutting Down")
        del self.cam
        self.finished_sig.emit(self.camera_index)
        self.q_thread.quit()

    @pyqtSlot()
    def getImage(self, save_images=True):
        if not self.acquiring:
            self.acquiring = True
            if self.active:
                self.status_sig.emit(self.camera_index, "Acquiring")
                ret, img = self.cam.read()
                
                self.stats["Minimum"] = np.min(img)
                self.stats["Maximum"] = np.max(img)
                self.stats["Mean"] = np.mean(img)
                self.stats["Median"] = np.median(img)
                now = time()
                self.stats['Frame Rate'] = 1/(now - self.last_frame_time)
                self.last_frame_time = now 

                self.imv.setImage(img, autoHistogramRange=True, autoLevels=True, autoRange=True, levelMode='mono')
                #np.copyto(self.img_data, img)
                #self.imv.autoLevels()

                self.stats_sig.emit(self.camera_index, self.stats)

                if self.save_images and save_images:
                        makedirs(self.save_path, exist_ok=True)
                        fn_base = path.normpath(path.join(self.save_path, f"ici_{self.camera_index}_{self.serial}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"))
                        fn_png = fn_base + ".png"

                        if self.save_png:
                            cv2.imwrite(fn_png, img)
                
                self.status_sig.emit(self.camera_index, "Ready")
                self.acquiring = False
            else:
                logging.warning("Skipping frames, try reducing sample frequency")

    @pyqtSlot(str, bool, bool, bool, float, float)
    def setSaveOpts(self, save_path, save_png, save_jpg, save_tiff, jpg_min, jpg_max):
        self.save_path = save_path
        self.save_png = save_png
        self.save_jpg = save_jpg
        self.save_tiff = save_tiff
        self.jpg_min = jpg_min
        self.jpg_max = jpg_max

    def getTypeString(self):
        return str(self.camera_index)
