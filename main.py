import sys
import ctypes
import os
from pathlib import Path
from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from views.main_window import MainWindow

my_app_id = 'mycompany.satellite.groundstation.1.0' 
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(my_app_id)

def main():
    load_dotenv(Path(__file__).with_name(".env"))
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("./docs/img/logo2.ico"))
    with open("views/style/style.qss", "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())
    window = MainWindow()
    window.show()
    runtime_log = os.getenv("EDUSAT_RUNTIME_LOG", "").strip()
    if runtime_log:
        def write_runtime_log(message):
            with open(runtime_log, "a", encoding="utf-8") as log_file:
                log_file.write(f"{message}\n")
                log_file.flush()
        window.controller.status_message.connect(write_runtime_log)
        window.controller.error_message.connect(write_runtime_log)
    auto_port = (os.getenv("EDUSAT_AUTO_CONNECT_PORT") or os.getenv("SERIAL_AUTO_CONNECT_PORT", "")).strip()
    if auto_port:
        def auto_connect():
            index = window.port_combo.findText(auto_port)
            if index >= 0:
                window.port_combo.setCurrentIndex(index)
            auto_baud = os.getenv("EDUSAT_AUTO_CONNECT_BAUD") or os.getenv("SERIAL_AUTO_CONNECT_BAUD", "115200")
            connected = window.controller.connect_serial(auto_port, int(auto_baud))
            window.connect_button.setText("Disconnect" if connected else "Connect")
        window._auto_connect = auto_connect
        QTimer.singleShot(250, window._auto_connect)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
