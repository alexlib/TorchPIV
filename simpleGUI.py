import logging
import traceback
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import LinearNDInterpolator
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QMessageBox
)
from torch import meshgrid
from PIVwidgets import ControlsWidget, show_message
from workers import PIVWorker

 

class MainWindow(QMainWindow):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.controls = ControlsWidget()
        self.controls.piv_button.clicked.connect(self.start_piv)
        self.controls.pause_button.clicked.connect(self.pause_piv)
        self.controls.stop_button.clicked.connect(self.stop_piv)
        self.calc_thread = None
        self.initUI()
   
    def initUI(self):

        layout = QVBoxLayout()
        layout.addWidget(self.controls)

        w = QWidget()
        w.setLayout(layout)
        self.setCentralWidget(w)

    def exit(self, checked):
        self.controls.close()
        exit()


    def reportProgress(self, value):
        self.controls.pbar.setValue(value)

    def reportFinish(self, output):
        show_message(
            f'Averaged data saved in\n{self.controls.settings.state.save_dir}'
            )
        x, y, u, v = output
        mod_V = np.hypot(u, v)
        Uq =  u/np.max(u)/6
        Vq =  v/np.max(v)/6
        avg = np.average(mod_V)
        
        img_data = plt.pcolormesh(x, y, mod_V, cmap=plt.get_cmap('jet'), 
                                    shading='auto', vmax=avg*2.5)
        plt.quiver(x, y, Uq, Vq, scale_units="xy", scale=.01, pivot="mid", width=0.002)

        x0 = x[0]
        y0 = y[:, 0]
        xi = np.linspace(x0.min(), x0.max(), x0.size)
        yi = np.linspace(y0.min(), y0.max(), y0.size)
        xflat = x.reshape(-1)
        yflat = y.reshape(-1)
        uflat = u.reshape(-1)
        vflat = v.reshape(-1)
        interp_ui = LinearNDInterpolator(list(zip(xflat, yflat)), uflat)
        interp_vi = LinearNDInterpolator(list(zip(xflat, yflat)), vflat)
        xi, yi = np.meshgrid(xi, yi)
        ui = interp_ui(xi, yi)
        vi = interp_vi(xi, yi)
        print(ui.shape)
        print(vi.shape)
        plt.streamplot(xi, yi, ui, vi, 
            density=5, linewidth=.5, arrowsize=.5
            )
        plt.axis("off")
        plt.colorbar(img_data)
        plt.show()
        
    
    def pause_piv(self):
        if self.calc_thread is None:
            return
        if self.worker.is_paused:
            text = "Pause"
        else:
            text = "Resume"

        self.controls.pause_button.setText(text)
        self.worker.is_paused = not self.worker.is_paused
    
    def stop_piv(self):
        if self.calc_thread is None:
            return
        self.worker.is_running = False
        self.controls.pbar.setValue(0)


    def start_piv(self):
        self.controls.settings.state.to_json()
        self.calc_thread = QThread(parent=None)
        piv_params = self.controls.settings.state
        if self.controls.regime_box.currentText() == "offline":
            self.worker = PIVWorker(self.controls.folder_name.toPlainText(),
                                    piv_params=piv_params)
        elif self.controls.regime_box.currentText() == "online":
            raise NotImplementedError()
            self.worker = OnlineWorker(self.controls.folder_name.toPlainText(),
                                        piv_params=piv_params)

        # self.worker.is_running = True
        # Step 4: Move worker to the thread
        self.worker.moveToThread(self.calc_thread)
        # Step 5: Connect signals and slots
        self.calc_thread.started.connect(self.worker.run)
        self.worker.signals.finished.connect(self.calc_thread.quit)
        self.worker.signals.finished.connect(self.worker.deleteLater)
        self.calc_thread.finished.connect(self.calc_thread.deleteLater)
        self.worker.signals.progress.connect(self.reportProgress)
        self.worker.signals.finished.connect(self.reportFinish)
        # Step 6: Start the thread
        self.calc_thread.start()

        # Final resets
        self._disable_buttons()
        self.calc_thread.finished.connect(
            self._enable_buttons
        )
    def _disable_buttons(self):
        self.controls.piv_button.setEnabled(False)
        self.controls.settings.confirm.setEnabled(False)

    
    def _enable_buttons(self):
        self.controls.piv_button.setEnabled(True)
        self.controls.settings.confirm.setEnabled(True)

    def message(self, string: str):
        print(string)


# basic logger functionality
log = logging.getLogger(__name__)
handler = logging.StreamHandler(stream=sys.stdout)
log.addHandler(handler)

def show_exception_box(log_msg):
    """Checks if a QApplication instance is available and shows a messagebox with the exception message. 
    If unavailable (non-console application), log an additional notice.
    """
    #NOT IMPLEMENTED
    def onclick(button):
        if button.text() == "OK":
            QApplication.exit()
        elif button.text() == "Retry":
            pass


    if QApplication.instance() is not None:
            errorbox = QMessageBox()
            errorbox.setIcon(QMessageBox.Critical)
            errorbox.setText(f"Oops. An unexpected error occured:\n{log_msg}")
            errorbox.setStandardButtons(QMessageBox.Ok)
            errorbox.buttonClicked.connect(onclick)
            errorbox.exec_()
    else:
        log.debug("No QApplication instance available.")


 
class UncaughtHook(QObject):
    _exception_caught = pyqtSignal(object)
 
    def __init__(self, *args, **kwargs):
        super(UncaughtHook, self).__init__(*args, **kwargs)

        # this registers the exception_hook() function as hook with the Python interpreter
        sys.excepthook = self.exception_hook

        # connect signal to execute the message box function always on main thread
        self._exception_caught.connect(show_exception_box)
 
    def exception_hook(self, exc_type, exc_value, exc_traceback):
        """Function handling uncaught exceptions.
        It is triggered each time an uncaught exception occurs. 
        """
        if issubclass(exc_type, KeyboardInterrupt):
            # ignore keyboard interrupt to support console applications
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        else:
            exc_info = (exc_type, exc_value, exc_traceback)
            log_msg = '\n'.join([''.join(traceback.format_tb(exc_traceback)),
                                 '{0}: {1}'.format(exc_type.__name__, exc_value)])
            log.critical("Uncaught exception:\n {0}".format(log_msg), exc_info=exc_info)

            # trigger message box show
            self._exception_caught.emit(log_msg)
 
# create a global instance of our class to register the hook
qt_exception_hook = UncaughtHook()



if __name__ == "__main__":
    
    app = QApplication(sys.argv)
    app.setStyle("fusion")
    app.setFont(QFont("Helvetica", 12))
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
    