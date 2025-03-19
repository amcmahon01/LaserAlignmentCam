import logging
import threading
from os import path, makedirs
from datetime import datetime
from time import sleep, time
from ctypes import sizeof, c_float

import numpy as np
from numpy.typing import NDArray
import cv2
import lmfit
from lmfit.lineshapes import gaussian2d
from scipy.stats import skew, norm
import debugpy

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, QThread, QTimer, QMutex
from PyQt6.QtWidgets import QApplication


class Camera_Search(QObject):
    result = pyqtSignal(list)
    finished = pyqtSignal()

    def __init__(self, skip_idxs=[]):
        QObject.__init__(self)

        self.skip_idxs = skip_idxs

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_Search")
        self.moveToThread(self.q_thread)
        self.q_thread.finished.connect(self.q_thread.deleteLater)
        self.finished.connect(self.deleteLater)
        self.finished.connect(self.q_thread.quit)
        self.q_thread.started.connect(self.findCameras)
        
    def findCameras(self):
        #https://stackoverflow.com/a/61768256
        # checks the first 10 indexes.
        debugpy.debug_this_thread()
        index = 0
        arr = []
        i = 10
        while i > 0:
            if index in self.skip_idxs:
                arr.append(index)
            else:
                try:
                    cap = cv2.VideoCapture(index)
                    if cap.read()[0]:
                        arr.append(index)
                        cap.release()
                except cv2.error as e:
                    if "Camera index out of range" in str(e):
                        pass
                except Exception as e:
                    logging.warning(f"Error opening camera {index}: {type(e)} {e}")
            index += 1
            i -= 1
        self.result.emit(arr)
        self.finished.emit()
        

class USB_Camera(QObject):
    ready_sig = pyqtSignal(int, bool)
    status_sig = pyqtSignal(int, str)
    stats_sig = pyqtSignal(int, dict)
    finished_sig = pyqtSignal(int)
    update_image_sig = pyqtSignal(int)

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

        #For testing only
        self.fake_update = 0
        self.fake_center_x = 0
        self.fake_center_y = 0
        self.fake_sig_x = 20
        self.fake_sig_y = 0

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_{camera_index}")
        self.moveToThread(self.q_thread)
        self.q_thread.finished.connect(self.threadFinished)

    @pyqtSlot()
    def init(self):
        threading.current_thread().name = QThread.currentThread().objectName()  #fix names
        debugpy.debug_this_thread()
        self.status_sig.emit(self.camera_index, "Starting")

        self.cam = cv2.VideoCapture()
        self.cam.setExceptionMode(True)

        try:
            self.cam.open(self.camera_index)

            self.width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.img = np.empty((self.width, self.height), dtype=np.uint8)

            logging.info(f"Started camera {self.camera_index}.")
            self.active = True
            self.ready_sig.emit(self.camera_index, True)
            self.status_sig.emit(self.camera_index, "Running")

            if not self.acquiring:
                self.acquiring = True
                self.stats = Camera_Stats(self.camera_index, self.img.T)    #Note the transpose!
                self.stats.stats_sig.connect(self.stats_sig)
                while self.active:
                    ret, img = self.cam.read()
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                    # For testing only
                    # img = np.zeros_like(img)
                    if self.fake_update % 180 == 0:
                        self.fake_center_x += img.shape[1] / 10
                        self.fake_center_y += img.shape[0] / 10
                        self.fake_sig_x += 10
                        self.fake_sig_y += 15

                        x_sub = np.arange(0, img.shape[1])
                        y_sub = np.arange(0, img.shape[0])
                        x, y = np.meshgrid(x_sub, y_sub)

                        self.fake_gauss = gaussian2d(x, y, amplitude=1, centerx=self.fake_center_x, centery=self.fake_center_y, sigmax=abs(self.fake_sig_x), sigmay=abs(self.fake_sig_y))
                        self.fake_gauss = (self.fake_gauss / np.max(self.fake_gauss)) * 255
                        self.fake_gauss += np.random.normal(0, 25, self.fake_gauss.shape)
                    img = np.clip(self.fake_gauss + (img * 0.5), 0, 255).astype(np.uint8)
                    self.fake_update += 1

                    np.copyto(self.img, img.T)
                    self.update_image_sig.emit(self.camera_index)    

                    #stats - update when processing thread is ready
                    if self.stats.mutex.tryLock():
                        self.stats.history["Minimum"] += [np.min(img)]
                        self.stats.history["Maximum"] += [np.max(img)]
                        self.stats.history["Mean"] += [np.mean(img)]
                        self.stats.history["frame_count"] = self.stats.history["frame_count"] + 1
                        self.stats.history["sums"] += img
                        self.stats.mutex.unlock()
        
                    QApplication.processEvents()

                self.stats.stop()
                self.acquiring = False

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
        self.active = False
        #self.acq_timer.stop()
        self.cam.release()
        logging.info(f"Stopped camera {self.camera_index}.")
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
    
    def threadFinished(self):
        del self.q_thread

    @pyqtSlot(str)
    def setSaveOpts(self, save_path):
        self.save_path = save_path

    def getTypeString(self):
        return str(self.camera_index)


class Camera_Stats(QObject):
    stats_sig = pyqtSignal(int, dict, dict)
    
    def __init__(self, camera_index: int, img: NDArray):
        QObject.__init__(self)
        self.camera_index = camera_index
        self.frame_rate = 15
        self.img_shape = img.shape
        self.mutex = QMutex()
        self.stats = {"Gaussian":{}}
        self.plots = {}
        self.history = {}

        self.fake_center_x = 0
        self.fake_center_y = 0
        self.fake_sig_x = -50
        self.fake_sig_y = -50

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Stats_Cam_{camera_index}")
        self.moveToThread(self.q_thread)
        self.q_thread.started.connect(self.init)
        self.q_thread.finished.connect(self.threadFinished)
        self.q_thread.start()

    @pyqtSlot()
    def init(self):
        threading.current_thread().name = QThread.currentThread().objectName()  #fix names
        debugpy.debug_this_thread()
        
        self.resetStats()
        self.stats_timer = QTimer()
        self.stats_timer.setInterval(500)
        self.stats_timer.timeout.connect(self.updateStats)
        self.stats_timer.start()
        logging.info(f"Started stats for camera {self.camera_index}.")

    @pyqtSlot()
    def updateStats(self):
        debugpy.debug_this_thread()
        self.mutex.lock()
        try:
            self.stats["Minimum"] = np.min(self.history["Minimum"])
            self.stats["Maximum"] = np.max(self.history["Maximum"])
            self.stats["Mean"] = np.mean(self.history["Mean"])        #NON-GENERALIZABLE STATS WARNING: ONLY ALLOWED BECAUSE ALL SAMPLES ARE IDENTICAL IN SIZE!
            self.stats['Frame Rate'] = self.history["frame_count"] / (self.stats_timer.interval() / 1000)
            img_means : NDArray = np.copy(self.history["sums"] / self.history["frame_count"])
        except ValueError:
            # this can occur during intialization if threads are out of sync
            img_means = np.zeros(self.img_shape, dtype=float)
            pass

        self.resetStats()
        self.mutex.unlock()

        subsampling = 2
        model = lmfit.models.Gaussian2dModel()
        x_sub = np.arange(0, img_means.shape[1], subsampling)
        y_sub = np.arange(0, img_means.shape[0], subsampling)
        z_sub = img_means[::subsampling,::subsampling]
        # x_sub = np.arange(0, img_means.shape[1])
        # y_sub = np.arange(0, img_means.shape[0])
        # z_sub = img_means
        x, y = np.meshgrid(x_sub, y_sub)

        # For testing only
        # self.fake_center_x += img_means.shape[0] / 10
        # self.fake_center_y += img_means.shape[1] / 10
        # self.fake_sig_x += 10
        # self.fake_sig_y += 10
        # z_sub = gaussian2d(x, y, amplitude=30, centerx=self.fake_center_x, centery=self.fake_center_y, sigmax=abs(self.fake_sig_x), sigmay=abs(self.fake_sig_y))

        params = model.guess(z_sub.flatten(), x.flatten(), y.flatten())
        result = model.fit(z_sub, x=x, y=y, calc_covar=False, params=params, max_nfev=5000)
        
        x_in_range = (result.params["centerx"].value > (img_means.shape[1] * -0.2)) and \
                     (result.params["centerx"].value < (img_means.shape[1] * 1.2))
        
        y_in_range = (result.params["centery"].value > (img_means.shape[0] * -0.2)) and \
                     (result.params["centery"].value < (img_means.shape[0] * 1.2))

        if result.rsquared > 0.5 and x_in_range and y_in_range and result.nfev < 5000:
            self.stats["Gaussian"]["Center X"] = result.params["centerx"].value
            self.stats["Gaussian"]["Center Y"] = result.params["centery"].value
            self.stats["Gaussian"]["Sigma X"] = result.params["sigmax"].value
            self.stats["Gaussian"]["Sigma Y"] = result.params["sigmay"].value
        else:
            self.stats["Gaussian"]["Center X"] = ""
            self.stats["Gaussian"]["Center Y"] = ""
            self.stats["Gaussian"]["Sigma X"] = ""
            self.stats["Gaussian"]["Sigma Y"] = ""
            
        self.stats["Gaussian"]["R^2"] = result.rsquared
        self.stats["Gaussian"]["Iterations"] = result.nfev

        self.stats_sig.emit(self.camera_index, self.stats, self.plots)


    def resetStats(self):
        self.history["Minimum"] = []
        self.history["Maximum"] = []
        self.history["Mean"] = []
        self.history["sums"] = np.zeros(self.img_shape, dtype=float)
        self.history["x_sums"] = []
        self.history["y_sums"] = []
        self.history["frame_count"] = 0

    def stop(self):
        self.stats_timer.stop()
        logging.info(f"Stopped stats for camera {self.camera_index}.")
        self.q_thread.quit()
        self.deleteLater()

    def threadFinished(self):
        del self.q_thread