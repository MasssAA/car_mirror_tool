#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import json
import time
import tempfile
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import xml.etree.ElementTree as ET

# 设置高DPI支持（Mac Retina屏幕）
if hasattr(Qt, 'AA_EnableHighDpiScaling'):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

class ADBHelper:
    """ADB 辅助类"""
    
    @staticmethod
    def execute_command(command):
        """执行ADB命令"""
        try:
            # Mac上确保使用正确的编码
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                env={**os.environ, 'LANG': 'en_US.UTF-8'}
            )
            return result.stdout.strip()
        except Exception as e:
            print(f"ADB命令执行失败: {e}")
            return None
    
    @staticmethod
    def check_adb():
        """检查ADB是否可用"""
        try:
            result = subprocess.run(['which', 'adb'], capture_output=True, text=True)
            if result.returncode != 0:
                return False, "ADB未安装"
            
            version = ADBHelper.execute_command("adb version")
            return True, version
        except:
            return False, "ADB检查失败"
    
    @staticmethod
    def get_devices():
        """获取连接的设备列表"""
        output = ADBHelper.execute_command("adb devices")
        devices = []
        if output:
            lines = output.split('\n')[1:]
            for line in lines:
                if '\tdevice' in line:
                    device_id = line.split('\t')[0]
                    # 获取设备型号
                    model = ADBHelper.execute_command(f"adb -s {device_id} shell getprop ro.product.model")
                    devices.append({
                        'id': device_id,
                        'model': model if model else device_id
                    })
        return devices
    
    @staticmethod
    def take_screenshot(device_id=None, output_path=None):
        """截取屏幕"""
        device_cmd = f"-s {device_id}" if device_id else ""
        
        if not output_path:
            output_path = os.path.join(tempfile.gettempdir(), f"screen_{int(time.time())}.png")
        
        # 截图并保存到设备
        ADBHelper.execute_command(f"adb {device_cmd} shell screencap -p /sdcard/screen_temp.png")
        
        # 拉取到本地
        ADBHelper.execute_command(f"adb {device_cmd} pull /sdcard/screen_temp.png {output_path}")
        
        # 清理设备上的临时文件
        ADBHelper.execute_command(f"adb {device_cmd} shell rm /sdcard/screen_temp.png")
        
        return output_path if os.path.exists(output_path) else None
    
    @staticmethod
    def dump_ui_hierarchy(device_id=None, output_path=None):
        """获取UI层级信息"""
        device_cmd = f"-s {device_id}" if device_id else ""
        
        if not output_path:
            output_path = os.path.join(tempfile.gettempdir(), f"ui_dump_{int(time.time())}.xml")
        
        # 使用uiautomator dump
        ADBHelper.execute_command(
            f"adb {device_cmd} shell uiautomator dump /sdcard/ui_dump_temp.xml"
        )
        
        # 拉取到本地
        ADBHelper.execute_command(
            f"adb {device_cmd} pull /sdcard/ui_dump_temp.xml {output_path}"
        )
        
        # 清理设备上的临时文件
        ADBHelper.execute_command(f"adb {device_cmd} shell rm /sdcard/ui_dump_temp.xml")
        
        return output_path if os.path.exists(output_path) else None
    
    @staticmethod
    def tap(x, y, device_id=None):
        """模拟点击"""
        device_cmd = f"-s {device_id}" if device_id else ""
        ADBHelper.execute_command(f"adb {device_cmd} shell input tap {x} {y}")
    
    @staticmethod
    def swipe(x1, y1, x2, y2, duration=300, device_id=None):
        """模拟滑动"""
        device_cmd = f"-s {device_id}" if device_id else ""
        ADBHelper.execute_command(f"adb {device_cmd} shell input swipe {x1} {y1} {x2} {y2} {duration}")
    
    @staticmethod
    def input_text(text, device_id=None):
        """输入文本"""
        device_cmd = f"-s {device_id}" if device_id else ""
        # 处理特殊字符
        text = text.replace(' ', '%s').replace('"', '\\"')
        ADBHelper.execute_command(f'adb {device_cmd} shell input text "{text}"')
    
    @staticmethod
    def press_key(keycode, device_id=None):
        """按键事件"""
        device_cmd = f"-s {device_id}" if device_id else ""
        ADBHelper.execute_command(f"adb {device_cmd} shell input keyevent {keycode}")

class UIParser:
    """UI解析器"""
    
    @staticmethod
    def parse_ui_xml(xml_file):
        """解析UI XML文件"""
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            return UIParser._parse_node(root)
        except Exception as e:
            print(f"解析XML失败: {e}")
            return None
    
    @staticmethod
    def _parse_node(node):
        """递归解析节点"""
        node_info = {
            'class': node.get('class', ''),
            'package': node.get('package', ''),
            'text': node.get('text', ''),
            'resource-id': node.get('resource-id', ''),
            'content-desc': node.get('content-desc', ''),
            'bounds': node.get('bounds', ''),
            'clickable': node.get('clickable', 'false'),
            'enabled': node.get('enabled', 'true'),
            'focusable': node.get('focusable', 'false'),
            'focused': node.get('focused', 'false'),
            'scrollable': node.get('scrollable', 'false'),
            'long-clickable': node.get('long-clickable', 'false'),
            'selected': node.get('selected', 'false'),
            'checkable': node.get('checkable', 'false'),
            'checked': node.get('checked', 'false'),
            'index': node.get('index', '0'),
            'children': []
        }
        
        # 解析bounds
        bounds_str = node_info['bounds']
        if bounds_str:
            import re
            matches = re.findall(r'\d+', bounds_str)
            if len(matches) == 4:
                node_info['x1'] = int(matches[0])
                node_info['y1'] = int(matches[1])
                node_info['x2'] = int(matches[2])
                node_info['y2'] = int(matches[3])
                node_info['center_x'] = (node_info['x1'] + node_info['x2']) // 2
                node_info['center_y'] = (node_info['y1'] + node_info['y2']) // 2
                node_info['width'] = node_info['x2'] - node_info['x1']
                node_info['height'] = node_info['y2'] - node_info['y1']
        
        # 递归解析子节点
        for child in node:
            child_info = UIParser._parse_node(child)
            if child_info:
                node_info['children'].append(child_info)
        
        return node_info
    
    @staticmethod
    def find_element_at_point(ui_data, x, y):
        """查找指定坐标的元素"""
        if not ui_data:
            return None
        
        elements = []
        UIParser._find_elements_at_point(ui_data, x, y, elements)
        
        # 返回最上层（最小）的元素
        if elements:
            return min(elements, key=lambda e: e.get('width', float('inf')) * e.get('height', float('inf')))
        return None
    
    @staticmethod
    def _find_elements_at_point(node, x, y, elements):
        """递归查找包含指定点的所有元素"""
        if 'x1' in node and 'y1' in node and 'x2' in node and 'y2' in node:
            if node['x1'] <= x <= node['x2'] and node['y1'] <= y <= node['y2']:
                elements.append(node)
        
        for child in node.get('children', []):
            UIParser._find_elements_at_point(child, x, y, elements)

class ClickableLabel(QLabel):
    """可点击的标签控件"""
    clicked = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.scale_factor = 1.0
        self.original_pixmap = None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.original_pixmap:
            # 获取相对于图片的实际坐标
            x = int(event.x() / self.scale_factor)
            y = int(event.y() / self.scale_factor)
            self.clicked.emit(x, y)
    
    def setPixmap(self, pixmap):
        self.original_pixmap = pixmap
        super().setPixmap(pixmap)

class CarScreenMirrorTool(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        super().__init__()
        self.current_device = None
        self.hierarchy_data = None
        self.screen_scale = 1.0
        self.auto_refresh = False
        self.tree_items_map = {}  # 存储节点数据到树节点的映射
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('车机投屏调试工具 - Mac版')
        self.setGeometry(100, 100, 1400, 900)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧投屏区域
        self.createScreenArea()
        main_layout.addWidget(self.screen_group, 2)
        
        # 右侧信息面板
        self.createInfoPanel()
        main_layout.addWidget(self.info_group, 1)
        
        # 创建状态栏
        self.status_bar = self.statusBar()
        
        # 创建定时器用于自动刷新
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.autoRefreshScreen)
        
        # 检查ADB并连接设备
        self.checkEnvironment()
        
    def createScreenArea(self):
        """创建投屏显示区域"""
        self.screen_group = QGroupBox("投屏画面")
        layout = QVBoxLayout()
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(200)
        toolbar.addWidget(QLabel("设备:"))
        toolbar.addWidget(self.device_combo)
        
        self.connect_btn = QPushButton("🔌 连接")
        self.connect_btn.clicked.connect(self.connectDevice)
        toolbar.addWidget(self.connect_btn)
        
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refreshScreen)
        toolbar.addWidget(self.refresh_btn)
        
        self.auto_refresh_cb = QCheckBox("自动刷新")
        self.auto_refresh_cb.stateChanged.connect(self.toggleAutoRefresh)
        toolbar.addWidget(self.auto_refresh_cb)

        # 添加实时控制复选框
        self.realtime_control_cb = QCheckBox("实时控制")
        self.realtime_control_cb.setToolTip("勾选后点击画面会实际控制车机，否则仅获取控件信息")
        toolbar.addWidget(self.realtime_control_cb)
        
        self.hierarchy_btn = QPushButton("🔍 分析UI")
        self.hierarchy_btn.clicked.connect(self.dumpHierarchy)
        toolbar.addWidget(self.hierarchy_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 投屏显示区域
        self.screen_label = ClickableLabel()
        self.screen_label.clicked.connect(self.onScreenClick)
        self.screen_label.setStyleSheet("border: 2px solid #ccc; background-color: #f0f0f0;")
        self.screen_label.setAlignment(Qt.AlignCenter)
        
        scroll = QScrollArea()
        scroll.setWidget(self.screen_label)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        layout.addWidget(scroll)
        
        # # 快捷操作栏
        # quick_toolbar = QHBoxLayout()
        
        # back_btn = QPushButton("◀ 返回")
        # back_btn.clicked.connect(lambda: self.sendKeyEvent(4))
        # quick_toolbar.addWidget(back_btn)
        
        # home_btn = QPushButton("🏠 主页")
        # home_btn.clicked.connect(lambda: self.sendKeyEvent(3))
        # quick_toolbar.addWidget(home_btn)
        
        # recent_btn = QPushButton("☰ 最近")
        # recent_btn.clicked.connect(lambda: self.sendKeyEvent(187))
        # quick_toolbar.addWidget(recent_btn)
        
        # quick_toolbar.addStretch()
        # layout.addLayout(quick_toolbar)
        
        self.screen_group.setLayout(layout)
        
    def createInfoPanel(self):
        """创建信息显示面板"""
        self.info_group = QGroupBox("控件信息")
        layout = QVBoxLayout()
        
        # 坐标信息
        coord_layout = QHBoxLayout()
        coord_layout.addWidget(QLabel("点击坐标:"))
        self.coord_label = QLabel("X: 0, Y: 0")
        self.coord_label.setStyleSheet("font-weight: bold;")
        coord_layout.addWidget(self.coord_label)
        coord_layout.addStretch()
        layout.addLayout(coord_layout)
        
        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # 控件信息表格
        layout.addWidget(QLabel("属性详情:"))
        self.info_table = QTableWidget()
        self.info_table.setColumnCount(2)
        self.info_table.setHorizontalHeaderLabels(["属性", "值"])
        self.info_table.horizontalHeader().setStretchLastSection(True)
        self.info_table.setAlternatingRowColors(True)
        layout.addWidget(self.info_table)
        
        # 层级树
        layout.addWidget(QLabel("UI层级树:"))
        self.hierarchy_tree = QTreeWidget()
        self.hierarchy_tree.setHeaderLabel("View Hierarchy")
        self.hierarchy_tree.itemClicked.connect(self.onTreeItemClicked)
        self.hierarchy_tree.setAlternatingRowColors(True)
        layout.addWidget(self.hierarchy_tree)
        
        # 搜索框
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索控件 (ID/Text/Class)...")
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.searchElement)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)
        
        self.info_group.setLayout(layout)
    
    def checkEnvironment(self):
        """检查环境配置"""
        # 检查ADB
        adb_ok, adb_info = ADBHelper.check_adb()
        if not adb_ok:
            QMessageBox.critical(self, "错误", 
                "ADB未安装或未配置！\n\n" +
                "请运行以下命令安装ADB:\n" +
                "brew install android-platform-tools")
            return
        
        # 刷新设备列表
        self.refreshDeviceList()
    
    def refreshDeviceList(self):
        """刷新设备列表"""
        devices = ADBHelper.get_devices()
        self.device_combo.clear()
        
        if devices:
            for device in devices:
                self.device_combo.addItem(f"{device['model']} ({device['id']})", device['id'])
            self.status_bar.showMessage(f"发现 {len(devices)} 个设备")
        else:
            self.device_combo.addItem("未发现设备")
            self.status_bar.showMessage("未检测到设备，请检查USB连接和调试模式")
    
    def connectDevice(self):
        """连接设备"""
        if self.device_combo.count() == 0:
            self.refreshDeviceList()
            return
        
        device_id = self.device_combo.currentData()
        if device_id:
            self.current_device = device_id
            self.refreshScreen()
            self.status_bar.showMessage(f"已连接到设备: {self.device_combo.currentText()}")
    
    def refreshScreen(self):
        """刷新屏幕截图"""
        if not self.current_device:
            self.connectDevice()
            return
        
        screenshot_path = ADBHelper.take_screenshot(self.current_device)
        if screenshot_path and os.path.exists(screenshot_path):
            pixmap = QPixmap(screenshot_path)
            
            # 计算缩放比例以适应窗口
            max_width = self.screen_label.parent().width() - 50
            max_height = self.screen_label.parent().height() - 100
            
            scale_w = max_width / pixmap.width() if pixmap.width() > max_width else 1.0
            scale_h = max_height / pixmap.height() if pixmap.height() > max_height else 1.0
            self.screen_scale = min(scale_w, scale_h, 1.0)
            
            if self.screen_scale < 1.0:
                scaled_pixmap = pixmap.scaled(
                    int(pixmap.width() * self.screen_scale),
                    int(pixmap.height() * self.screen_scale),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            else:
                scaled_pixmap = pixmap
            
            self.screen_label.scale_factor = self.screen_scale
            self.screen_label.setPixmap(scaled_pixmap)
            self.screen_label.resize(scaled_pixmap.size())
            
            # 清理临时文件
            try:
                os.remove(screenshot_path)
            except:
                pass
            
            self.status_bar.showMessage(f"屏幕已刷新 ({pixmap.width()}x{pixmap.height()})")
    
    def toggleAutoRefresh(self, state):
        """切换自动刷新"""
        if state == Qt.Checked:
            self.refresh_timer.start(1000)  # 每秒刷新
            self.auto_refresh = True
        else:
            self.refresh_timer.stop()
            self.auto_refresh = False
    
    def autoRefreshScreen(self):
        """自动刷新屏幕"""
        if self.auto_refresh and self.current_device:
            self.refreshScreen()
    
    def dumpHierarchy(self):
        """获取UI层级信息"""
        if not self.current_device:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        
        self.status_bar.showMessage("正在分析UI层级...")
        QApplication.processEvents()
        
        ui_file = ADBHelper.dump_ui_hierarchy(self.current_device)
        if ui_file and os.path.exists(ui_file):
            self.hierarchy_data = UIParser.parse_ui_xml(ui_file)
            self.updateHierarchyTree()
            
            # 清理临时文件
            try:
                os.remove(ui_file)
            except:
                pass
            
            self.status_bar.showMessage("UI层级分析完成")
        else:
            self.status_bar.showMessage("获取UI层级失败")
    
    def onScreenClick(self, x, y):
        """处理屏幕点击事件"""
        self.coord_label.setText(f"X: {x}, Y: {y}")
        
        # 查找并显示点击位置的元素
        if self.hierarchy_data:
            element = UIParser.find_element_at_point(self.hierarchy_data, x, y)
            if element:
                self.displayElementInfo(element)
                
                # 在树中展开并选中对应的节点
                self.expandToElement(element)
        
        # 发送点击事件到设备
        if self.current_device and self.realtime_control_cb.isChecked():
            ADBHelper.tap(x, y, self.current_device)
            
            # 如果开启了自动刷新，延迟一下再刷新
            if self.auto_refresh:
                QTimer.singleShot(500, self.refreshScreen)
    
    def expandToElement(self, element):
        """展开到指定元素并选中"""
        # 使用element的id作为键查找对应的树节点
        element_id = id(element)
        if element_id in self.tree_items_map:
            tree_item = self.tree_items_map[element_id]
            
            # 清除之前的选择
            self.hierarchy_tree.clearSelection()
            
            # 先折叠所有顶级节点
            root = self.hierarchy_tree.invisibleRootItem()
            for i in range(root.childCount()):
                self.collapseAllChildren(root.child(i))
            
            # 收集需要展开的路径上的所有节点
            path_to_expand = []
            current = tree_item
            while current:
                path_to_expand.append(current)
                current = current.parent()
            
            # 从根到目标节点依次展开
            for node in reversed(path_to_expand):
                if node.parent():  # 不展开根节点本身
                    node.parent().setExpanded(True)
            
            # 判断是否有子节点
            if tree_item.childCount() > 0:
                # 有子节点，展开当前节点
                tree_item.setExpanded(True)
                
                # 选中第一个子节点（或最后一个子节点）
                # first_child = tree_item.child(0)  # 选择第一个子节点
                last_child = tree_item.child(tree_item.childCount() - 1)  # 选择最后一个子节点
                last_child.setSelected(True)
                
                # 滚动到子节点
                self.hierarchy_tree.scrollToItem(last_child, QAbstractItemView.PositionAtCenter)
            else:
                # 没有子节点，直接选中当前节点
                tree_item.setSelected(True)
                
                # 滚动到该节点
                self.hierarchy_tree.scrollToItem(tree_item, QAbstractItemView.PositionAtCenter)
                
                # 滚动到该节点
                self.hierarchy_tree.scrollToItem(tree_item, QAbstractItemView.PositionAtCenter)

    def collapseAllChildren(self, item):
        """递归折叠所有子节点"""
        item.setExpanded(False)
        for i in range(item.childCount()):
            self.collapseAllChildren(item.child(i))
    
    def displayElementInfo(self, element):
        """显示元素信息"""
        self.info_table.setRowCount(0)
        
        # 要显示的属性
        properties = [
            ('Class', 'class'),
            ('ID', 'resource-id'),
            ('Text', 'text'),
            ('Content-Desc', 'content-desc'),
            ('Bounds', 'bounds'),
            ('Size', None),  # 特殊处理
            ('Clickable', 'clickable'),
            ('Enabled', 'enabled'),
            ('Focusable', 'focusable'),
            ('Scrollable', 'scrollable'),
            ('Package', 'package'),
            ('Index', 'index')
        ]
        
        for prop_name, prop_key in properties:
            if prop_key:
                value = element.get(prop_key, '')
            elif prop_name == 'Size' and 'width' in element:
                value = f"{element['width']} x {element['height']}"
            else:
                continue
                
            if value:  # 只显示非空属性
                row = self.info_table.rowCount()
                self.info_table.insertRow(row)
                self.info_table.setItem(row, 0, QTableWidgetItem(prop_name))
                
                # 对于长文本，创建可复制的项
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.info_table.setItem(row, 1, item)
    
    def updateHierarchyTree(self):
        """更新层级树"""
        self.hierarchy_tree.clear()
        self.tree_items_map.clear()  # 清空映射
        
        if self.hierarchy_data:
            root_item = QTreeWidgetItem(self.hierarchy_tree)
            self._buildTreeItem(root_item, self.hierarchy_data)
            self.hierarchy_tree.expandToDepth(2)  # 默认展开两层
    
    def _buildTreeItem(self, parent_item, node_data):
        """构建树节点"""
        # 设置节点显示文本
        class_name = node_data.get('class', '').split('.')[-1]
        text = node_data.get('text', '')
        resource_id = node_data.get('resource-id', '').split('/')[-1] if node_data.get('resource-id') else ''
        
        display_text = class_name
        if resource_id:
            display_text += f" [{resource_id}]"
        if text:
            display_text += f" - {text[:30]}"
        
        parent_item.setText(0, display_text)
        parent_item.setData(0, Qt.UserRole, node_data)
        
        # 保存节点数据到树节点的映射
        self.tree_items_map[id(node_data)] = parent_item
        
        # 设置图标颜色以区分不同类型
        if 'Button' in class_name:
            parent_item.setForeground(0, QBrush(QColor(0, 122, 204)))
        elif 'Text' in class_name:
            parent_item.setForeground(0, QBrush(QColor(52, 152, 219)))
        elif 'Image' in class_name:
            parent_item.setForeground(0, QBrush(QColor(46, 204, 113)))
        
        # 递归添加子节点
        for child in node_data.get('children', []):
            child_item = QTreeWidgetItem(parent_item)
            self._buildTreeItem(child_item, child)
    
    def onTreeItemClicked(self, item, column):
        """处理树节点点击"""
        node_data = item.data(0, Qt.UserRole)
        if node_data:
            self.displayElementInfo(node_data)
    
    def searchElement(self):
        """搜索元素"""
        search_text = self.search_input.text().lower()
        if not search_text or not self.hierarchy_data:
            return
        
        # 递归搜索
        results = []
        self._searchInNode(self.hierarchy_data, search_text, results)
        
        if results:
            # 显示第一个结果
            self.displayElementInfo(results[0])
            
            # 展开到第一个结果
            self.expandToElement(results[0])
            
            self.status_bar.showMessage(f"找到 {len(results)} 个匹配项")
        else:
            self.status_bar.showMessage("未找到匹配的元素")
    
    def _searchInNode(self, node, search_text, results):
        """递归搜索节点"""
        # 检查各个属性
        if (search_text in node.get('resource-id', '').lower() or
            search_text in node.get('text', '').lower() or
            search_text in node.get('class', '').lower() or
            search_text in node.get('content-desc', '').lower()):
            results.append(node)
        
        # 递归搜索子节点
        for child in node.get('children', []):
            self._searchInNode(child, search_text, results)
    
    def sendKeyEvent(self, keycode):
        """发送按键事件"""
        if self.current_device and self.realtime_control_cb.isChecked():
            ADBHelper.press_key(keycode, self.current_device)
            if self.auto_refresh:
                QTimer.singleShot(500, self.refreshScreen)

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建并显示主窗口
    window = CarScreenMirrorTool()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
