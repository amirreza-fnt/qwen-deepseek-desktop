from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.ui.main_window import Window

def test_farsi_blue_code_copy(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'history.db'); cid=store.create(); store.add(cid,'assistant','نمونه:\n\n```python\nprint(42)\n```\n\nو `x = 1`')
    window=Window(store); window.cid=cid; window.render()
    assert window.options['theme']=='Light'
    assert 'گفت‌وگوی جدید' in window.new.text()
    assert window.code_blocks == ['print(42)', 'x = 1']
    assert 'کپی کد' in window.chat.toPlainText()
    links=[]; block=window.chat.document().begin()
    while block.isValid():
        fragment=block.begin()
        while not fragment.atEnd():
            if fragment.fragment().charFormat().isAnchor():
                links.append(fragment.fragment().charFormat().anchorHref())
            fragment+=1
        block=block.next()
    assert 'copy-code:0' in links and 'copy-code:1' in links
    window.copy_code_link(QUrl('copy-code:0'))
    assert QApplication.clipboard().text() == 'print(42)'
    window.copy_code_link(QUrl('copy-code:1'))
    assert QApplication.clipboard().text() == 'x = 1'
    window.close()
