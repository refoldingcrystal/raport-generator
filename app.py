import sys
import os
import shutil
import uuid
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget,
    QFileDialog, QLineEdit
)
from PyQt6.QtCore import Qt
import re
import typst

IMAGE_EXTENSIONS = {".png", ".jpg", ".gif", ".svg", ".webp"}
PATTERN_DOUBLE = "#pagebreak()\n#table(\n\t[{}], [{}],\n\timage(\"{}\"), image(\"{}\")\n)\n"
PATTERN_SINGLE = "#pagebreak()\n#table(columns: 1,\n\t[{}], image(\"{}\")\n)\n"


class FileTreeItem(QTreeWidgetItem):
    def __init__(self, path, is_dir, parent=None):
        super().__init__(parent)
        self.path = path
        self.is_dir = is_dir
        self.setText(0, os.path.basename(path) or path)
        self.setCheckState(0, Qt.CheckState.Unchecked)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Raport generator")
        self.resize(900, 600)
        self._updating_checks = False
        self._selected_paths = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        self.choose_btn = QPushButton("Choose directory")
        self.choose_btn.clicked.connect(self.choose_directory)
        top_row.addWidget(self.choose_btn)

        self.text_input = QLineEdit("%d %f")
        self.text_input.setPlaceholderText("Pattern")
        self.text_input.textChanged.connect(self.update_file_list)
        top_row.addWidget(self.text_input)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Selected directory")
        self.tree.itemChanged.connect(self.on_item_changed)
        splitter.addWidget(self.tree)

        self.file_list = QListWidget()
        splitter.addWidget(self.file_list)

        splitter.setSizes([450, 450])
        layout.addWidget(splitter)

        # Bottom: print button
        self.print_btn = QPushButton("Generate")
        self.print_btn.clicked.connect(self.generate)
        layout.addWidget(self.print_btn)

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.load_directory(directory)

    def load_directory(self, path):
        self.tree.blockSignals(True)
        self.tree.clear()
        root_item = FileTreeItem(path, is_dir=True)
        self.tree.addTopLevelItem(root_item)
        has_children = self.populate_tree(root_item, path)
        if has_children:
            root_item.setExpanded(True)
        self.tree.blockSignals(False)
        self.update_file_list()

    def populate_tree(self, parent_item, path):
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return False

        added_any = False
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                dir_item = FileTreeItem(entry.path, is_dir=True, parent=parent_item)
                has_children = self.populate_tree(dir_item, entry.path)
                if has_children:
                    dir_item.setExpanded(True)
                    added_any = True
                else:
                    parent_item.removeChild(dir_item)
            else:
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    FileTreeItem(entry.path, is_dir=False, parent=parent_item)
                    added_any = True

        return added_any

    def on_item_changed(self, item, column):
        if column != 0 or self._updating_checks:
            return
        self._updating_checks = True
        state = item.checkState(0)
        self.set_children_check_state(item, state)
        self.update_parent_check_state(item)
        self._updating_checks = False
        self.update_file_list()

    def set_children_check_state(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self.set_children_check_state(child, state)

    def update_parent_check_state(self, item):
        parent = item.parent()
        if parent is None:
            return
        checked = sum(
            1 for i in range(parent.childCount())
            if parent.child(i).checkState(0) == Qt.CheckState.Checked
        )
        total = parent.childCount()
        if checked == 0:
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        elif checked == total:
            parent.setCheckState(0, Qt.CheckState.Checked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        self.update_parent_check_state(parent)

    def collect_checked_files(self, item, result):
        if not item.is_dir and item.checkState(0) == Qt.CheckState.Checked:
            result.append(item.path)
        for i in range(item.childCount()):
            self.collect_checked_files(item.child(i), result)

    def format_path(self, path):
        pattern = r'^[\d\s\-]+|[\s\-]*\(.*?\)$|[\s\-]*$'
        directory = re.sub(pattern, '', os.path.basename(os.path.dirname(path)))
        filename = re.sub(pattern, '', os.path.splitext(os.path.basename(path))[0])
        pattern = self.text_input.text()
        return pattern.replace('%d', directory).replace('%f', filename)        

    def update_file_list(self):
        self.file_list.clear()
        files = []
        for i in range(self.tree.topLevelItemCount()):
            self.collect_checked_files(self.tree.topLevelItem(i), files)
        self._selected_paths = files
        self.file_list.addItems([self.format_path(path) for path in files])

    def generate(self):
        template_file = QFileDialog.getOpenFileName(self, "Generate report", "", "Typst Files (*.typ)")[0]
        if not template_file:
            return
        files = [(self.format_path(path), os.path.relpath(path, os.path.dirname(template_file)).replace('\\', '/')) for path in self._selected_paths]

        with open(template_file, 'r', encoding='utf-8') as f:
            template_content = f.read()
        base, ext = os.path.splitext(template_file)
        output_file = base + "-generated" + ext
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(template_content + '\n')
            for i in range(0, len(files), 2):
                if i + 1 < len(files):
                    line = PATTERN_DOUBLE.format(files[i][0], files[i + 1][0], files[i][1], files[i + 1][1])
                else:
                    line = PATTERN_SINGLE.format(files[i][0], files[i][1])
                f.write(line)

        typst.compile(output_file, output=base+".pdf", root=os.path.dirname(output_file))



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())