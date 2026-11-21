from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QTimer
app = QApplication([])
w = QLabel('Qt loaded successfully')
w.show()
print('QT_IMPORT_OK', flush=True)
QTimer.singleShot(1000, app.quit)
app.exec()
