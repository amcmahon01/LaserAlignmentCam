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

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, QThread, QTimer


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
    ready_sig = pyqtSignal(int, bool)
    status_sig = pyqtSignal(int, str)
    stats_sig = pyqtSignal(int, dict)
    finished_sig = pyqtSignal(int)
    update_image_sig = pyqtSignal(int, object)

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
        self.frame_rate = 15
        
        self.stats = {}

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_{camera_index}")
        self.moveToThread(self.q_thread)


    @pyqtSlot()
    def init(self):
        threading.current_thread().name = QThread.currentThread().objectName()  #fix names
        self.status_sig.emit(self.camera_index, "Starting")

        self.acq_timer = QTimer()
        self.acq_timer.setInterval(int(1000/self.frame_rate))
        self.acq_timer.timeout.connect(self.getImage)

        self.cam = cv2.VideoCapture()
        self.cam.setExceptionMode(True)

        try:
            self.cam.open(self.camera_index)

            self.width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_rate = int(self.cam.get(cv2.CAP_PROP_XI_FRAMERATE))
            if frame_rate > 0:
                self.frame_rate = frame_rate
            self.acq_timer.setInterval(int(1000/self.frame_rate))
            #self.serial = self.getCameraSerialNumber()


            #Insane initialization to get autoLevels
            # self.imv.setImage(self.img_data, autoHistogramRange=True, autoLevels=True, levelMode='mono')
            # temperature_image = self.getTemperatureImage()
            # img = np.reshape(temperature_image.cast('f'), (self.height, self.width))
            # np.copyto(self.img_data, img.T)
            # self.imv.getHistogramWidget().imageChanged(autoLevel=True)
            # self.imv.normRadioChanged()
                        
            logging.info(f"Started camera {self.camera_index}.")
            self.active = True
            self.ready_sig.emit(self.camera_index, True)
            self.status_sig.emit(self.camera_index, "Running")
            self.acq_timer.start()

        except Exception as e:
            logging.error(f"Error starting camera {self.camera_index}: {type(e)} {e}")
            try:
                self.cam.release()
            except Exception:
                pass
            self.status_sig.emit(self.camera_index, "Error")
            self.ready_sig.emit(self.camera_index, False)



    @pyqtSlot()    
    def stop(self):
        self.status_sig.emit(self.camera_index, "Stopping")
        self.acq_timer.stop()
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
        try:
            del self.cam
        except AttributeError:
            pass
        self.status_sig.emit(self.camera_index, "Standby")
        self.finished_sig.emit(self.camera_index)
        self.q_thread.quit()

    @pyqtSlot()
    def getImage(self, save_images=True):
        if not self.acquiring:
            self.acquiring = True
            if self.active:
                ret, img = self.cam.read()
                
                self.stats["Minimum"] = np.min(img)
                self.stats["Maximum"] = np.max(img)
                self.stats["Mean"] = np.mean(img)
                self.stats["Median"] = np.median(img)
                now = time()
                self.stats['Frame Rate'] = 1/(now - self.last_frame_time)
                self.last_frame_time = now 

                self.update_image_sig.emit(self.camera_index, img)
                #np.copyto(self.img_data, img)
                #self.imv.autoLevels()

                self.stats_sig.emit(self.camera_index, self.stats)

                if self.save_images and save_images:
                        makedirs(self.save_path, exist_ok=True)
                        fn_base = path.normpath(path.join(self.save_path, f"cam_{self.serial}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"))
                        fn_png = fn_base + ".png"

                        if self.save_png:
                            cv2.imwrite(fn_png, img)
                
                self.acquiring = False
            else:
                logging.warning("Skipping frames, try reducing sample frequency")

    @pyqtSlot(str)
    def setSaveOpts(self, save_path):
        self.save_path = save_path

    def getTypeString(self):
        return str(self.camera_index)
