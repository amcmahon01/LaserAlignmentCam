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
from scipy.stats import skew
import debugpy

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, QThread, QTimer
from PyQt6.QtWidgets import QApplication


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
        self.q_thread.quit()


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
        self.frame_rate = 15
        
        self.stats = {}
        self.stats_history = {}

        self.q_thread : QThread = QThread()
        self.q_thread.setObjectName(f"Cam_{camera_index}")
        self.moveToThread(self.q_thread)


    @pyqtSlot()
    def init(self):
        threading.current_thread().name = QThread.currentThread().objectName()  #fix names
        debugpy.debug_this_thread()
        self.status_sig.emit(self.camera_index, "Starting")

        self.stats_timer = QTimer()
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self.updateStats)

        self.cam = cv2.VideoCapture()
        self.cam.setExceptionMode(True)

        try:
            self.cam.open(self.camera_index)

            self.width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.img = np.empty((self.width, self.height), dtype=np.uint8)

            frame_rate = int(self.cam.get(cv2.CAP_PROP_XI_FRAMERATE))
            if frame_rate > 0:
                self.frame_rate = frame_rate
            #self.acq_timer.setInterval(int(1000/self.frame_rate))
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
            self.getImage()
            #self.acq_timer.start()

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

    @pyqtSlot()
    def getImage(self, save_images=True):
        if not self.acquiring:
            self.acquiring = True
            self.resetStats()
            self.stats_timer.start()

            while self.active:
                ret, img = self.cam.read()
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                np.copyto(self.img, img.T)
                self.update_image_sig.emit(self.camera_index)    

                #stats
                self.stats_history["Minimum"] += [np.min(img)]
                self.stats_history["Maximum"] += [np.max(img)]
                self.stats_history["Mean"] += [np.mean(img)]
                self.frame_count = self.frame_count + 1

                self.stats_history["sums"] += self.img
                self.stats_history["x_sums"] = [np.sum(img, axis=0)]
                self.stats_history["y_sums"] = [np.sum(img, axis=1)]
       
                QApplication.processEvents()

                # if self.save_images and save_images:
                #         makedirs(self.save_path, exist_ok=True)
                #         fn_base = path.normpath(path.join(self.save_path, f"cam_{self.serial}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"))
                #         fn_png = fn_base + ".png"

                #         if self.save_png:
                #             cv2.imwrite(fn_png, img)
            self.stats_timer.stop()
            self.acquiring = False

    @pyqtSlot(str)
    def setSaveOpts(self, save_path):
        self.save_path = save_path

    def getTypeString(self):
        return str(self.camera_index)

    @pyqtSlot()
    def updateStats(self):
        self.stats["Minimum"] = np.min(self.stats_history["Minimum"])
        self.stats["Maximum"] = np.max(self.stats_history["Maximum"])
        self.stats["Mean"] = np.mean(self.stats_history["Mean"])        #NON-GENERALIZABLE STATS WARNING: ONLY ALLOWED BECAUSE ALL SAMPLES ARE IDENTICAL IN SIZE!
        self.stats['Frame Rate'] = self.frame_count / (self.stats_timer.interval() / 1000)
        self.stats_sig.emit(self.camera_index, self.stats)

        img_means : NDArray = self.stats_history["sums"] / self.frame_count

        # model = lmfit.models.Gaussian2dModel()
        # x_sub = np.arange(0, img_means.shape[1], 64)
        # y_sub = np.arange(0, img_means.shape[0], 64)
        # z_sub = img_means[::64,::64]
        # x, y = np.meshgrid(x_sub, y_sub)
        # #z = gaussian2d(x, y, amplitude=30, centerx=320, centery=240, sigmax=64, sigmay=64)

        # params = model.guess(z_sub.flatten(), x.flatten(), y.flatten())
        # result = model.fit(z_sub, x=x, y=y, calc_covar=False, params=params, weights=1/np.sqrt(z_sub+1))

        # self.stats["Amplitude"] = result.params["amplitude"].value
        # self.stats["Center X"] = result.params["centerx"].value
        # self.stats["Center Y"] = result.params["centery"].value
        # self.stats["FWHM X"] = result.params["fwhmx"].value
        # self.stats["FWHM Y"] = result.params["fwhmy"].value
    
        self.resetStats()

        # x_gauss_params, covar = fit_gaussian(self.stats_history["x_sums"])
        # x_amp, x_center, x_sd = x_gauss_params
        # y_gauss_params, covar = fit_gaussian(self.stats_history["y_sums"])
        # y_amp, y_center, y_sd = y_gauss_params

        # self.stats["X Offset From Origin"]
        # self.stats["X Skew"] = skew(self.stats_history["x_sums"], axis=0, bias=True)
        # self.stats["Y Skew"] = skew(self.stats_history["y_sums"], axis=0, bias=True)

    def resetStats(self):
        self.stats_history["Minimum"] = []
        self.stats_history["Maximum"] = []
        self.stats_history["Mean"] = []
        self.stats_history["sums"] = np.zeros_like(self.img)
        self.stats_history["x_sums"] = []
        self.stats_history["y_sums"] = []
        self.frame_count = 0

def gaussian(x, amplitude, mean, std_dev):
    """
    Gaussian function.
    
    Parameters:
    x : array_like
        Independent variable where the data is measured.
    amplitude : float
        Amplitude of the Gaussian function.
    mean : float
        Mean (center) of the Gaussian function.
    std_dev : float
        Standard deviation (width) of the Gaussian function.
        
    Returns:
    y : array_like
        Dependent variable values calculated from the Gaussian function.
    """
    return amplitude * np.exp(-((x - mean) ** 2 / (2 * std_dev ** 2)))

def fit_gaussian(data):
    """
    Fit a Gaussian to a 1D array of data.
    
    Parameters:
    data : array_like
        The 1D array of data points to fit the Gaussian to.
        
    Returns:
    params : tuple
        Tuple containing the parameters (amplitude, mean, std_dev) of the fitted Gaussian.
    covariance : ndarray
        Covariance matrix of the parameters.
    """
    # Create an array of indices for the x values
    x = np.arange(len(data))
    
    # Initial guess for the parameters: [amplitude, mean, std_dev]
    initial_guess = [np.max(data), len(data) / 2, len(data) / 4]
    
    # Fit the Gaussian function to the data
    params, covariance = curve_fit(gaussian, x, data, p0=initial_guess)
    
    return params, covariance