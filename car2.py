#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import json
import time
import tempfile
import re
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import xml.etree.ElementTree as ET

# 设置高DPI支持（Mac Retina屏幕）
if hasattr(Qt, 'AA_EnableHighDpiScaling'):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

class ParseMode(Enum):
    """解析模式枚举"""
    HYBRID = "混合模式 (推荐)"
    UIAUTOMATOR = "UIAutomator"
    VIEW_HIERARCHY = "View Hierarchy"

class HybridUIParser:
    """混合UI解析器：以View Hierarchy为基础，补充UIAutomator的文本信息"""
    
    def __init__(self):
        self.ui_tree = None  # UIAutomator的树
        self.vh_tree = None  # View Hierarchy的树（主要基础）
        self.matched_count = 0
        self.unmatched_count = 0
        self.ui_node_map = {}  # UI节点的映射表
        
    def parse_uiautomator(self, xml_file):
        """解析UIAutomator XML文件"""
        try:
            self.ui_tree = UIParser.parse_ui_xml(xml_file)
            return self.ui_tree
        except Exception as e:
            print(f"解析UIAutomator XML失败: {e}")
            return None
    
    def parse_view_hierarchy(self, hierarchy_text):
        """解析View Hierarchy"""
        parser = ViewHierarchyParser(hierarchy_text)
        parser.parse()
        self.vh_tree = parser.to_ui_format()
        return self.vh_tree
    
    def merge_trees(self):
        """合并两个树的主入口"""
        if not self.vh_tree or not self.ui_tree:
            print("错误：缺少必要的树数据")
            return None
        
        # 1. 查找content节点作为起点
        vh_content = self._find_content_node(self.vh_tree)
        ui_content = self._find_content_node(self.ui_tree)
        
        if not vh_content:
            print("警告：VH树中未找到content节点，使用整个树")
            vh_content = self.vh_tree
        else:
            print("✓ VH树：找到content节点")
            
        if not ui_content:
            print("警告：UI树中未找到content节点，使用整个树")
            ui_content = self.ui_tree
        else:
            print("✓ UI树：找到content节点")
        
        print("\n" + "=" * 80)
        print("开始合并UI树...")
        print("=" * 80)
        
        # 2. 构建UI节点的索引
        self._build_ui_index(ui_content)
        
        # 3. 执行匹配
        self._match_and_merge(vh_content, ui_content, 0)
        
        # 4. 输出统计
        self._print_statistics()
        
        return vh_content
    
    def _find_content_node(self, node):
        """递归查找第一个id为content的节点"""
        if not node:
            return None
            
        resource_id = node.get('resource-id', '')
        if resource_id and ('content' in resource_id or resource_id.endswith(':id/content')):
            return node
        
        for child in node.get('children', []):
            result = self._find_content_node(child)
            if result:
                return result
                
        return None
    
    def _build_ui_index(self, ui_node, level=0):
        """构建UI节点的索引，方便快速查找"""
        if not ui_node:
            return
        
        # 按照ID建立索引
        resource_id = ui_node.get('resource-id', '')
        if resource_id:
            id_suffix = self._extract_id_suffix(resource_id)
            if id_suffix:
                if id_suffix not in self.ui_node_map:
                    self.ui_node_map[id_suffix] = []
                self.ui_node_map[id_suffix].append(ui_node)
        
        # 递归处理子节点
        for child in ui_node.get('children', []):
            self._build_ui_index(child, level + 1)
    
    def _extract_id_suffix(self, full_id):
        """提取ID的后缀部分"""
        if not full_id:
            return None
        
        if ':id/' in full_id:
            return full_id.split(':id/')[-1]
        elif '/' in full_id:
            return full_id.split('/')[-1]
        else:
            return full_id
    
    def _match_and_merge(self, vh_node, ui_context, level=0):
        """匹配并合并节点"""
        if not vh_node:
            return
        
        indent = "  " * level
        
        # 1. 尝试找到匹配的UI节点
        matched_ui = self._find_best_match(vh_node, ui_context, level)
        
        if matched_ui:
            # 匹配成功，补充信息
            self.matched_count += 1
            self._supplement_text_info(vh_node, matched_ui)
            
            vh_summary = self._get_node_summary(vh_node)
            ui_summary = self._get_node_summary(matched_ui)
            print(f"{indent}✓ 匹配: {vh_summary} <-> {ui_summary}")
            
            # 递归处理子节点
            vh_children = vh_node.get('children', [])
            for vh_child in vh_children:
                self._match_and_merge(vh_child, matched_ui, level + 1)
        else:
            # 未匹配，但保留VH节点
            self.unmatched_count += 1
            vh_node['text_matched'] = False
            
            vh_summary = self._get_node_summary(vh_node)
            print(f"{indent}✗ 未匹配: {vh_summary}")
            
            # 递归处理子节点
            vh_children = vh_node.get('children', [])
            for vh_child in vh_children:
                self._match_and_merge(vh_child, ui_context, level + 1)
    
    def _find_best_match(self, vh_node, ui_context, level):
        """查找最佳匹配的UI节点"""
        candidates = []
        
        # 策略1：通过ID查找
        vh_id = vh_node.get('resource-id', '')
        if vh_id:
            id_suffix = self._extract_id_suffix(vh_id)
            if id_suffix and id_suffix in self.ui_node_map:
                for ui_node in self.ui_node_map[id_suffix]:
                    if self._is_node_available(ui_node):
                        score = self._calculate_match_score(vh_node, ui_node, True)
                        candidates.append((ui_node, score))
        
        # 策略2：在上下文的子树中查找
        if ui_context:
            self._search_in_subtree(vh_node, ui_context, candidates, level)
        
        # 选择得分最高的候选
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_match, score = candidates[0]
            
            # 只有得分超过阈值才认为匹配成功
            if score >= 0.5:
                # 标记节点已被使用
                self._mark_node_used(best_match)
                return best_match
        
        return None
    
    def _search_in_subtree(self, vh_node, ui_root, candidates, level, max_depth=2, current_depth=0):
        """在UI子树中搜索匹配的节点"""
        if not ui_root or current_depth > max_depth:
            return
        
        # 检查当前节点
        if self._is_node_available(ui_root):
            score = self._calculate_match_score(vh_node, ui_root, False)
            if score > 0:
                candidates.append((ui_root, score))
        
        # 递归检查子节点
        for ui_child in ui_root.get('children', []):
            self._search_in_subtree(vh_node, ui_child, candidates, level, max_depth, current_depth + 1)
    
    def _calculate_match_score(self, vh_node, ui_node, has_same_id):
        """计算两个节点的匹配得分"""
        score = 0.0
        
        # 1. ID匹配（权重40%）
        if has_same_id:
            score += 0.4
        
        # 2. 类名匹配（权重30%）
        vh_class = vh_node.get('class', '').split('.')[-1]
        ui_class = ui_node.get('class', '').split('.')[-1]
        
        if vh_class == ui_class:
            score += 0.3
        elif self._similar_class_names(vh_class, ui_class):
            score += 0.2
        
        # 3. 子节点数量相似度（权重15%）
        vh_child_count = len(vh_node.get('children', []))
        ui_child_count = len(ui_node.get('children', []))
        
        if vh_child_count == ui_child_count:
            score += 0.15
        elif vh_child_count > 0 and ui_child_count > 0:
            similarity = min(vh_child_count, ui_child_count) / max(vh_child_count, ui_child_count)
            score += 0.15 * similarity
        
        # 4. 属性相似度（权重15%）
        attr_score = 0
        attr_count = 0
        
        for attr in ['clickable', 'focusable', 'enabled', 'scrollable']:
            if vh_node.get(attr) == ui_node.get(attr):
                attr_score += 1
            attr_count += 1
        
        if attr_count > 0:
            score += 0.15 * (attr_score / attr_count)
        
        return score
    
    def _similar_class_names(self, class1, class2):
        """判断两个类名是否相似"""
        if class1 == class2:
            return True
        
        # 类型组映射
        type_groups = {
            'text': ['TextView', 'EditText', 'TextInputEditText', 'AppCompatTextView'],
            'button': ['Button', 'ImageButton', 'AppCompatButton', 'MaterialButton'],
            'image': ['ImageView', 'AppCompatImageView', 'ImageButton'],
            'layout': ['LinearLayout', 'RelativeLayout', 'FrameLayout', 'ConstraintLayout'],
            'container': ['RecyclerView', 'ListView', 'ScrollView', 'ViewPager'],
        }
        
        # 检查是否属于同一类型组
        for group_name, class_list in type_groups.items():
            class1_in_group = any(c in class1 for c in class_list)
            class2_in_group = any(c in class2 for c in class_list)
            if class1_in_group and class2_in_group:
                return True
        
        return False
    
    def _is_node_available(self, node):
        """检查节点是否可用（未被标记为已使用）"""
        return not node.get('_used', False)
    
    def _mark_node_used(self, node):
        """标记节点为已使用"""
        node['_used'] = True
    
    def _supplement_text_info(self, vh_node, ui_node):
        """用UIAutomator的信息补充View Hierarchy节点"""
        if not ui_node:
            return
        
        # 1. 同步文本信息
        ui_text = ui_node.get('text', '')
        ui_content_desc = ui_node.get('content-desc', '')
        
        if ui_content_desc:
            vh_node['content-desc'] = ui_content_desc
            vh_node['text_source'] = 'content-desc'
        elif ui_text:
            vh_node['content-desc'] = ui_text
            vh_node['text_source'] = 'text'
        
        vh_node['text'] = ui_text
        
        # 2. 使用UIAutomator的resource-id（如果VH的不完整）
        ui_resource_id = ui_node.get('resource-id', '')
        if ui_resource_id and not vh_node.get('resource-id'):
            vh_node['resource-id'] = ui_resource_id
        
        # 3. 同步状态属性
        for attr in ['clickable', 'long-clickable', 'checkable', 'checked', 
                    'selected', 'enabled', 'focusable', 'focused', 
                    'scrollable']:
            if attr in ui_node:
                vh_node[attr] = ui_node[attr]
        
        # 4. 标记已补充信息
        vh_node['info_supplemented'] = True
        vh_node['text_matched'] = True
    
    def _get_node_summary(self, node):
        """获取节点摘要信息"""
        if not node:
            return "None"
        
        class_name = node.get('class', '').split('.')[-1][:20]
        resource_id = self._extract_id_suffix(node.get('resource-id', ''))
        text = node.get('text', '')[:15]
        content_desc = node.get('content-desc', '')[:15]
        
        summary = class_name
        if resource_id:
            summary += f"#{resource_id}"
        if text:
            summary += f"'{text}'"
        elif content_desc:
            summary += f"[{content_desc}]"
        
        return summary
    
    def _print_statistics(self):
        """打印匹配统计信息"""
        total = self.matched_count + self.unmatched_count
        if total > 0:
            match_rate = (self.matched_count / total) * 100
            print("\n" + "=" * 80)
            print(f"匹配统计:")
            print(f"  - 成功匹配: {self.matched_count}")
            print(f"  - 未匹配: {self.unmatched_count}")
            print(f"  - 总节点数: {total}")
            print(f"  - 匹配率: {match_rate:.1f}%")
            print("=" * 80)
    
    def get_statistics(self):
        """获取匹配统计信息"""
        total = self.matched_count + self.unmatched_count
        return {
            'matched': self.matched_count,
            'unmatched': self.unmatched_count,
            'total': total,
            'match_rate': f"{self.matched_count / total * 100:.1f}%" if total > 0 else "0%"
        }

class ViewHierarchyParser:
    """View Hierarchy 解析器（保留用于兼容）"""
    
    # 定义需要过滤的控件ID和类名
    FILTER_IDS = [
        'action_mode_bar_stub',
        'navigationBarBackground', 
        'statusBarBackground'
    ]
    
    FILTER_CLASSES = [
        'android.view.IndicatorBar'
    ]
    
    def __init__(self, hierarchy_text: str):
        self.hierarchy_text = hierarchy_text
        self.views = []
        # 创建一个虚拟根节点，所有解析到的控件都是它的子节点
        self.root = self._create_virtual_root()
        
    def _create_virtual_root(self):
        """创建虚拟根节点"""
        return {
            'class': 'RootNode',
            'resource-id': '',
            'text': '',
            'content-desc': '',
            'bounds': '[0,0][0,0]',
            'clickable': 'false',
            'enabled': 'true',
            'focusable': 'false',
            'scrollable': 'false',
            'package': '',
            'index': '0',
            'x1': 0,
            'y1': 0,
            'x2': 0,
            'y2': 0,
            'center_x': 0,
            'center_y': 0,
            'width': 0,
            'height': 0,
            'children': []  # 所有顶级控件都会被添加到这里
        }
    
    def _should_filter(self, view_info):
        """判断是否应该过滤掉该控件"""
        # 检查resource_id
        if view_info.get('resource_id'):
            for filter_id in self.FILTER_IDS:
                if filter_id in view_info['resource_id']:
                    return True
        
        # 检查类名
        if view_info.get('class'):
            for filter_class in self.FILTER_CLASSES:
                if filter_class == view_info['class']:
                    return True
        
        # 检查尺寸是否为0x0
        if view_info.get('bounds_parsed'):
            bounds = view_info['bounds_parsed']
            width = bounds['right'] - bounds['left']
            height = bounds['bottom'] - bounds['top']
            if width == 0 and height == 0:
                return True
        
        return False
        
    def parse(self) -> List[Dict]:
        """解析View Hierarchy并计算所有控件的绝对坐标"""
        lines = self.hierarchy_text.split('\n')
        
        # 用栈来跟踪父控件
        parent_stack = []
        nodes_stack = []  # UI节点栈，用于构建树结构
        skip_children_until_indent = -1  # 用于跳过被过滤控件的子控件
        
        for line in lines:
            if not line.strip() or 'View Hierarchy:' in line:
                continue
                
            # 计算缩进级别（每个空格算一级）
            indent_level = len(line) - len(line.lstrip())
            
            # 如果当前是被过滤控件的子控件，跳过
            if skip_children_until_indent >= 0:
                if indent_level > skip_children_until_indent:
                    continue
                else:
                    # 已经退出被过滤控件的子树
                    skip_children_until_indent = -1
            
            # 解析控件信息
            view_info = self._parse_line(line.strip())
            if not view_info:
                continue
            
            #检查是否应该过滤
            if self._should_filter(view_info):
                # 记录这个缩进级别，跳过它的所有子控件
                skip_children_until_indent = indent_level
                
                # 打印过滤信息
                filter_reason = ""
                if view_info.get('resource_id') and any(fid in view_info['resource_id'] for fid in self.FILTER_IDS):
                    filter_reason = f"ID: {view_info['resource_id']}"
                elif view_info.get('class') in self.FILTER_CLASSES:
                    filter_reason = f"类名: {view_info['class']}"
                elif view_info.get('bounds_parsed'):
                    bounds = view_info['bounds_parsed']
                    width = bounds['right'] - bounds['left']
                    height = bounds['bottom'] - bounds['top']
                    if width == 0 and height == 0:
                        filter_reason = "尺寸: 0x0"
                
                print(f"过滤控件: {view_info['class']} - {filter_reason}")
                continue
            
            # 根据缩进级别维护父控件栈
            while len(parent_stack) > 0 and parent_stack[-1]['indent'] >= indent_level:
                parent_stack.pop()
                if nodes_stack:
                    nodes_stack.pop()
            
            # 计算绝对坐标
            if parent_stack:
                parent = parent_stack[-1]
                view_info['absolute_bounds'] = self._calculate_absolute_bounds(
                    parent['absolute_bounds'], 
                    view_info['bounds']
                )
                view_info['parent_bounds'] = parent['absolute_bounds']
            else:
                # 顶级控件，相对坐标就是绝对坐标
                view_info['absolute_bounds'] = view_info['bounds']
                view_info['parent_bounds'] = None
            
            # 添加缩进信息和层级
            view_info['indent'] = indent_level
            view_info['level'] = len(parent_stack)
            view_info['original_line'] = line
            
            # 创建UI节点（兼容UIParser格式）
            ui_node = self._create_ui_node(view_info)
            
            # 再次检查绝对坐标后的尺寸（以防计算后变成0x0）
            if ui_node['width'] == 0 and ui_node['height'] == 0:
                skip_children_until_indent = indent_level
                print(f"过滤控件（绝对坐标后）: {view_info['class']} - 尺寸: 0x0")
                continue
            
            # 建立父子关系
            if nodes_stack:
                # 有父节点，添加为子节点
                parent_node = nodes_stack[-1]
                parent_node['children'].append(ui_node)
            else:
                # 没有父节点，这是顶级控件，添加到虚拟根节点下
                self.root['children'].append(ui_node)
            
            # 将当前节点加入栈
            nodes_stack.append(ui_node)
            
            # 将当前控件信息加入栈
            parent_stack.append(view_info)
            
            # 保存控件信息
            self.views.append(view_info)
        
        return self.views
    
    def _create_ui_node(self, view_info):
        """创建UI节点（兼容UIParser格式）"""
        # 使用绝对坐标而不是相对坐标
        abs_bounds = view_info['absolute_bounds']
        match = re.match(r'(\d+),(\d+)-(\d+),(\d+)', abs_bounds)
        
        # 处理resource-id
        resource_id = ''
        if view_info.get('resource_id'):
            # 如果是content，确保能被识别
            if view_info['resource_id'] == 'content':
                resource_id = 'app:id/content'
            else:
                resource_id = f"app:id/{view_info['resource_id']}"
        
        node = {
            'class': view_info['class'],
            'resource-id': resource_id,
            'text': '',  # View Hierarchy 中没有text信息
            'content-desc': '',
            'bounds': '',  # 初始为空
            'clickable': str(view_info.get('clickable', False)).lower(),
            'enabled': str(view_info.get('enabled', True)).lower(),
            'focusable': str(view_info.get('focusable', False)).lower(),
            'scrollable': 'false',
            'package': '',
            'index': '0',
            'children': []  # 重要：初始化children列表
        }
        
        # 设置坐标信息
        if match:
            left = int(match.group(1))
            top = int(match.group(2))
            right = int(match.group(3))
            bottom = int(match.group(4))
            
            node['bounds'] = f"[{left},{top}][{right},{bottom}]"
            node['x1'] = left
            node['y1'] = top
            node['x2'] = right
            node['y2'] = bottom
            node['center_x'] = (left + right) // 2
            node['center_y'] = (top + bottom) // 2
            node['width'] = right - left
            node['height'] = bottom - top
        else:
            # 如果没有匹配到坐标，设置默认值
            node['x1'] = 0
            node['y1'] = 0
            node['x2'] = 0
            node['y2'] = 0
            node['center_x'] = 0
            node['center_y'] = 0
            node['width'] = 0
            node['height'] = 0
        
        return node
    
    def _parse_line(self, line: str) -> Optional[Dict]:
        """解析单行控件信息"""
        view_info = {}
        
        # 提取类名 - 支持内部类的$符号
        class_match = re.match(r'^([a-zA-Z0-9.$_]+)', line)
        if class_match:
            view_info['class'] = class_match.group(1)
        else:
            return None
        
        # 提取bounds (坐标)
        bounds_match = re.search(r'(\d+),(\d+)-(\d+),(\d+)', line)
        if bounds_match:
            view_info['bounds'] = bounds_match.group(0)
            view_info['bounds_parsed'] = {
                'left': int(bounds_match.group(1)),
                'top': int(bounds_match.group(2)),
                'right': int(bounds_match.group(3)),
                'bottom': int(bounds_match.group(4))
            }
        else:
            return None
        
        # 提取resource-id
        id_match = re.search(r'#[a-f0-9]+ (?:app|android):id/([a-zA-Z0-9_]+)', line)
        if id_match:
            view_info['resource_id'] = id_match.group(1)
        else:
            view_info['resource_id'] = None
        
        # 提取实例hash
        hash_match = re.search(r'\{([a-f0-9]+)', line)
        if hash_match:
            view_info['instance_hash'] = hash_match.group(1)
        
        # 提取可见性和其他属性
        view_info['visible'] = 'V.' in line
        view_info['focusable'] = '.F' in line
        view_info['enabled'] = '.E' in line
        view_info['clickable'] = '.C' in line or 'Button' in view_info['class'] or 'TextView' in view_info['class']
        
        return view_info
    
    def _calculate_absolute_bounds(self, parent_bounds: str, child_bounds: str) -> str:
        """计算子控件的绝对坐标"""
        # 解析父控件坐标
        parent_match = re.match(r'(\d+),(\d+)-(\d+),(\d+)', parent_bounds)
        if not parent_match:
            return child_bounds
        
        p_left = int(parent_match.group(1))
        p_top = int(parent_match.group(2))
        
        # 解析子控件相对坐标
        child_match = re.match(r'(\d+),(\d+)-(\d+),(\d+)', child_bounds)
        if not child_match:
            return child_bounds
        
        c_left = int(child_match.group(1))
        c_top = int(child_match.group(2))
        c_right = int(child_match.group(3))
        c_bottom = int(child_match.group(4))
        
        # 计算绝对坐标
        abs_left = p_left + c_left
        abs_top = p_top + c_top
        abs_right = p_left + c_right
        abs_bottom = p_top + c_bottom
        
        return f"{abs_left},{abs_top}-{abs_right},{abs_bottom}"
    
    def to_ui_format(self) -> Dict:
        """返回根节点（已经是UI格式）"""
        # 如果只有一个真实的根节点，可以直接返回它
        if len(self.root['children']) == 1:
            return self.root['children'][0]
        # 否则返回虚拟根节点
        return self.root

# ADBHelper、UIParser、ClickableLabel类保持不变...
# 这里省略了这些类的代码，它们与原代码完全相同

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
    def get_view_hierarchy(device_id=None, target_activity="X01MainActivity"):
        """获取指定Activity的View Hierarchy（旧方法，保留用于兼容）"""
        device_cmd = f"-s {device_id}" if device_id else ""
        
        print(f"获取 {target_activity} 的View Hierarchy...")
        output = ADBHelper.execute_command(
            f"adb {device_cmd} shell dumpsys activity top"
        )
        
        if not output:
            print("未获取到输出")
            return None
        
        # 查找包含目标Activity的View Hierarchy
        search_start = 0
        while True:
            hierarchy_start = output.find("View Hierarchy:", search_start)
            if hierarchy_start == -1:
                break
            
            # 检查下一行是否包含目标 Activity
            first_newline = output.find('\n', hierarchy_start)
            if first_newline == -1:
                break
            
            second_newline = output.find('\n', first_newline + 1)
            if second_newline == -1:
                second_line = output[first_newline + 1:]
            else:
                second_line = output[first_newline + 1:second_newline]
            
            # 检查第二行是否包含目标 Activity
            if "DecorView@" in second_line and f"[{target_activity}]" in second_line:
                # 找到了目标 View Hierarchy，现在确定结束位置
                # 使用"Looper"作为结束标记
                hierarchy_end = output.find("Looper", hierarchy_start + 1)
                
                if hierarchy_end == -1:
                    hierarchy_text = output[hierarchy_start:]
                else:
                    hierarchy_text = output[hierarchy_start:hierarchy_end]
                
                return hierarchy_text
            
            # 继续查找下一个 "View Hierarchy:"
            search_start = hierarchy_start + 1
        
        print(f"未找到包含 {target_activity} 的View Hierarchy")
        return None
    
    @staticmethod
    def dump_ui_automator(device_id=None):
        """使用uiautomator dump获取当前页面的完整UI层次结构（新方法）"""
        device_cmd = f"-s {device_id}" if device_id else ""
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = "ui_dumps"
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        remote_file = "/sdcard/ui_dump.xml"
        local_file = os.path.join(output_dir, f"ui_dump_{timestamp}.xml")
        
        try:
            # 1. 在设备上生成UI dump
            print("📱 正在获取UI层次结构...")
            dump_result = ADBHelper.execute_command(
                f"adb {device_cmd} shell uiautomator dump {remote_file}"
            )
            
            if "dumped to" in dump_result.lower():
                print(f"✅ UI dump已生成到设备: {remote_file}")
            
            # 2. 将文件从设备拉取到本地
            print("📥 正在下载文件到本地...")
            ADBHelper.execute_command(
                f"adb {device_cmd} pull {remote_file} \"{local_file}\""
            )
            
            print(f"✅ 文件已保存到: {local_file}")
            
            # 3. 清理设备上的临时文件
            ADBHelper.execute_command(f"adb {device_cmd} shell rm {remote_file}")
            
            return local_file
            
        except Exception as e:
            print(f"❌ 获取UI dump失败: {e}")
            return None
    
    @staticmethod
    def get_current_activity(device_id=None):
        """获取当前Activity信息"""
        device_cmd = f"-s {device_id}" if device_id else ""
        
        try:
            # 方法1：使用dumpsys activity activities（最可靠）
            cmd = f"adb {device_cmd} shell dumpsys activity activities"
            output = ADBHelper.execute_command(cmd)
            
            if output:
                # 查找mResumedActivity或mFocusedActivity
                for line in output.split('\n'):
                    if 'mResumedActivity' in line or 'mFocusedActivity' in line:
                        import re
                        # 匹配包名/Activity名格式
                        match = re.search(r'([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.]+)', line)
                        if match:
                            package_name = match.group(1)
                            activity_name = match.group(2)
                            # 如果Activity名以.开头，补全包名
                            if activity_name.startswith('.'):
                                activity_name = package_name + activity_name
                            full_name = f"{package_name}/{activity_name}"
                            print(f"✅ 当前Activity: {full_name}")
                            return full_name
            
            # 方法2：使用dumpsys window
            cmd = f"adb {device_cmd} shell dumpsys window windows"
            output = ADBHelper.execute_command(cmd)
            
            if output:
                for line in output.split('\n'):
                    if 'mCurrentFocus=' in line or 'mFocusedApp=' in line:
                        import re
                        match = re.search(r'([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.]+)', line)
                        if match:
                            full_name = f"{match.group(1)}/{match.group(2)}"
                            print(f"✅ 当前Activity: {full_name}")
                            return full_name
            
            print("❌ 无法获取当前Activity信息")
            return None
            
        except Exception as e:
            print(f"❌ 获取Activity信息失败: {e}")
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
        ADBHelper.execute_command(f"adb {device_cmd} pull /sdcard/screen_temp.png \"{output_path}\"")
        
        # 清理设备上的临时文件
        ADBHelper.execute_command(f"adb {device_cmd} shell rm /sdcard/screen_temp.png")
        
        return output_path if os.path.exists(output_path) else None
    
    @staticmethod
    def tap(x, y, device_id=None):
        """模拟点击"""
        device_cmd = f"-s {device_id}" if device_id else ""
        ADBHelper.execute_command(f"adb {device_cmd} shell input tap {x} {y}")
    
    @staticmethod
    def input_text(text, device_id=None):
        """输入文本"""
        device_cmd = f"-s {device_id}" if device_id else ""
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
    hovered = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.scale_factor = 1.0
        self.original_pixmap = None
        self.hover_rect = None
        self.click_rect = None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.original_pixmap:
            x = int(event.x() / self.scale_factor)
            y = int(event.y() / self.scale_factor)
            self.clicked.emit(x, y)

    def mouseMoveEvent(self, event):
        if self.original_pixmap:
            x = int(event.x() / self.scale_factor)
            y = int(event.y() / self.scale_factor)
            self.hovered.emit(x, y)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if not self.pixmap():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.hover_rect:
            pen = QPen(QColor(0, 122, 255), 2)
            pen.setStyle(Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(0, 122, 255, 30)))
            painter.drawRect(self.hover_rect)
        
        if self.click_rect:
            pen = QPen(QColor(255, 0, 0), 3)
            pen.setStyle(Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(255, 0, 0, 30)))
            painter.drawRect(self.click_rect)
    
    def setHoverRect(self, rect):
        self.hover_rect = rect
        self.update()
    
    def setClickRect(self, rect):
        self.click_rect = rect
        self.update()
    
    def clearRects(self):
        self.hover_rect = None
        self.click_rect = None
        self.update()

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
        self.tree_items_map = {}
        self.parse_mode = ParseMode.HYBRID  # 默认混合模式
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
        
        # 添加分隔符
        toolbar.addWidget(QLabel(" | "))
        
        # UI分析按钮组
        ui_group = QHBoxLayout()
        
        # 添加解析模式选择
        ui_group.addWidget(QLabel("解析模式:"))
        self.parse_mode_combo = QComboBox()
        self.parse_mode_combo.setMinimumWidth(150)
        for mode in ParseMode:
            self.parse_mode_combo.addItem(mode.value, mode)
        self.parse_mode_combo.currentIndexChanged.connect(self.onParseModeChanged)
        ui_group.addWidget(self.parse_mode_combo)
        
        self.hierarchy_btn = QPushButton("🔍 分析UI")
        self.hierarchy_btn.clicked.connect(self.dumpHierarchy)
        ui_group.addWidget(self.hierarchy_btn)
        
        toolbar.addLayout(ui_group)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 投屏显示区域
        self.screen_label = ClickableLabel()
        self.screen_label.clicked.connect(self.onScreenClick)
        self.screen_label.hovered.connect(self.onScreenHover)
        self.screen_label.setStyleSheet("border: 2px solid #ccc; background-color: #f0f0f0;")
        self.screen_label.setAlignment(Qt.AlignCenter)
        
        scroll = QScrollArea()
        scroll.setWidget(self.screen_label)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        layout.addWidget(scroll)
        
        self.screen_group.setLayout(layout)
    
    def onParseModeChanged(self, index):
        """解析模式改变时的处理"""
        self.parse_mode = self.parse_mode_combo.currentData()
        self.status_bar.showMessage(f"已切换到{self.parse_mode.value}")
        print(f"\n切换解析模式: {self.parse_mode.value}")
    
    def onScreenHover(self, x, y):
        """处理鼠标悬停事件"""
        if self.hierarchy_data:
            element = UIParser.find_element_at_point(self.hierarchy_data, x, y)
            if element and 'x1' in element:
                rect = QRect(
                    int(element['x1'] * self.screen_label.scale_factor),
                    int(element['y1'] * self.screen_label.scale_factor),
                    int(element['width'] * self.screen_label.scale_factor),
                    int(element['height'] * self.screen_label.scale_factor)
                )
                self.screen_label.setHoverRect(rect)
            else:
                self.screen_label.setHoverRect(None)

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
        adb_ok, adb_info = ADBHelper.check_adb()
        if not adb_ok:
            QMessageBox.critical(self, "错误", 
                "ADB未安装或未配置！\n\n" +
                "请运行以下命令安装ADB:\n" +
                "brew install android-platform-tools")
            return
        
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
        
        self.screen_label.clearRects()
    
        screenshot_path = ADBHelper.take_screenshot(self.current_device)
        if screenshot_path and os.path.exists(screenshot_path):
            pixmap = QPixmap(screenshot_path)
            
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
            
            try:
                os.remove(screenshot_path)
            except:
                pass
            
            self.status_bar.showMessage(f"屏幕已刷新 ({pixmap.width()}x{pixmap.height()})")
    
    def toggleAutoRefresh(self, state):
        """切换自动刷新"""
        if state == Qt.Checked:
            self.refresh_timer.start(1000)
            self.auto_refresh = True
        else:
            self.refresh_timer.stop()
            self.auto_refresh = False
    
    def autoRefreshScreen(self):
        """自动刷新屏幕"""
        if self.auto_refresh and self.current_device:
            self.refreshScreen()
    
    def dumpHierarchy(self):
        """根据选择的模式获取UI层级信息"""
        if not self.current_device:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        
        # 清理所有旧数据
        self.hierarchy_data = None
        self.screen_label.clearRects()
        self.hierarchy_tree.clear()
        self.tree_items_map.clear()
        self.info_table.setRowCount(0)
        
        print("\n" + "=" * 80)
        print(f"开始分析UI - {self.parse_mode.value}")
        print("=" * 80)
        
        # 根据模式选择不同的解析方法
        if self.parse_mode == ParseMode.HYBRID:
            self._parseHybridMode()
        elif self.parse_mode == ParseMode.UIAUTOMATOR:
            self._parseUIAutomatorMode()
        elif self.parse_mode == ParseMode.VIEW_HIERARCHY:
            self._parseViewHierarchyMode()
        
        print("\nUI分析流程结束")
        print("=" * 80 + "\n")
    
    def _parseHybridMode(self):
        """混合模式解析"""
        self.status_bar.showMessage("正在进行混合模式分析...")
        QApplication.processEvents()
        
        # 1. 获取UIAutomator数据
        print("步骤1: 获取UIAutomator数据...")
        ui_file = ADBHelper.dump_ui_automator(self.current_device)
        
        # 2. 获取View Hierarchy数据
        print("步骤2: 获取View Hierarchy数据...")
        hierarchy_text = None
        
        # 自动获取当前Activity
        current_activity_info = ADBHelper.get_current_activity(self.current_device)
        if current_activity_info and '/' in current_activity_info:
            parts = current_activity_info.split('/')
            activity_name = parts[1] if len(parts) > 1 else parts[0]
            if '.' in activity_name:
                activity_name = activity_name.split('.')[-1]
            
            hierarchy_text = ADBHelper.get_view_hierarchy(self.current_device, activity_name)
        
        # 3. 处理获取的数据
        if not hierarchy_text and not ui_file:
            self.status_bar.showMessage("获取UI数据失败")
            print("错误：无法获取UI数据")
            return
        
        if not hierarchy_text:
            # 降级到UIAutomator模式
            print("警告：View Hierarchy获取失败，降级到UIAutomator模式")
            self._parseUIAutomatorMode()
            return
        
        if not ui_file or not os.path.exists(ui_file):
            # 降级到View Hierarchy模式
            print("警告：UIAutomator获取失败，降级到View Hierarchy模式")
            self._parseViewHierarchyMode()
            return
        
        # 4. 混合模式分析
        print("步骤3: 混合模式分析...")
        self.status_bar.showMessage("正在合并数据...")
        QApplication.processEvents()
        
        hybrid_parser = HybridUIParser()
        
        # 解析View Hierarchy（作为主要基础）
        hybrid_parser.parse_view_hierarchy(hierarchy_text)
        
        # 解析UIAutomator（用于补充信息）
        hybrid_parser.parse_uiautomator(ui_file)
        
        # 合并树
        print("\n开始合并UI树...")
        self.hierarchy_data = hybrid_parser.merge_trees()
        
        if self.hierarchy_data:
            self.updateHierarchyTree()
            
            # 显示统计信息
            stats = hybrid_parser.get_statistics()
            print("\n" + "=" * 80)
            print(f"分析完成！")
            print(f"  - 文本信息匹配: {stats['matched']} 个节点")
            print(f"  - 未匹配: {stats['unmatched']} 个节点")
            print(f"  - 匹配率: {stats['match_rate']}")
            print("=" * 80)
            
            self.status_bar.showMessage(
                f"混合分析完成 - 匹配率: {stats['match_rate']} "
                f"(成功: {stats['matched']}, 未匹配: {stats['unmatched']})"
            )
    
    def _parseUIAutomatorMode(self):
        """纯UIAutomator模式解析"""
        self.status_bar.showMessage("正在进行UIAutomator分析...")
        QApplication.processEvents()
        
        print("获取UIAutomator数据...")
        ui_file = ADBHelper.dump_ui_automator(self.current_device)
        
        if ui_file and os.path.exists(ui_file):
            self.hierarchy_data = UIParser.parse_ui_xml(ui_file)
            
            if self.hierarchy_data:
                self.updateHierarchyTree()
                # 统计控件数量
                total_elements = self.countElements(self.hierarchy_data)
                self.status_bar.showMessage(f"UIAutomator分析完成，找到 {total_elements} 个控件")
                print(f"UIAutomator分析完成，找到 {total_elements} 个控件")
            else:
                self.status_bar.showMessage("UI层级解析失败")
        else:
            self.status_bar.showMessage("获取UI层级失败")
    
    def _parseViewHierarchyMode(self):
        """纯View Hierarchy模式解析"""
        self.status_bar.showMessage("正在进行View Hierarchy分析...")
        QApplication.processEvents()
        
        print("获取View Hierarchy数据...")
        hierarchy_text = None
        
        # 自动获取当前Activity
        current_activity_info = ADBHelper.get_current_activity(self.current_device)
        
        if current_activity_info and '/' in current_activity_info:
            parts = current_activity_info.split('/')
            activity_name = parts[1] if len(parts) > 1 else parts[0]
            if '.' in activity_name:
                activity_name = activity_name.split('.')[-1]
            
            hierarchy_text = ADBHelper.get_view_hierarchy(self.current_device, activity_name)
        
        if not hierarchy_text:
            # 提供手动输入选项
            activity_input, ok = QInputDialog.getText(
                self,
                "输入Activity名称",
                "无法自动获取Activity，请手动输入:",
                QLineEdit.Normal,
                "MainActivity"
            )
            
            if ok and activity_input:
                hierarchy_text = ADBHelper.get_view_hierarchy(self.current_device, activity_input)
        
        if hierarchy_text:
            # 解析View Hierarchy
            parser = ViewHierarchyParser(hierarchy_text)
            views = parser.parse()
            
            if views:
                self.hierarchy_data = parser.to_ui_format()
                if self.hierarchy_data:
                    self.updateHierarchyTree()
                    self.status_bar.showMessage(f"View Hierarchy分析完成，找到 {len(views)} 个控件")
                    print(f"View Hierarchy分析完成，找到 {len(views)} 个控件")
                else:
                    self.status_bar.showMessage("View Hierarchy转换失败")
            else:
                self.status_bar.showMessage("View Hierarchy解析失败")
        else:
            self.status_bar.showMessage("获取View Hierarchy失败")
    
    def countElements(self, node):
        """递归计算元素总数"""
        count = 1  # 当前节点
        for child in node.get('children', []):
            count += self.countElements(child)
        return count
    
    def onScreenClick(self, x, y):
        """处理屏幕点击事件"""
        self.coord_label.setText(f"X: {x}, Y: {y}")
        
        if self.hierarchy_data:
            element = UIParser.find_element_at_point(self.hierarchy_data, x, y)
            if element:
                self.displayElementInfo(element)
                self.expandToElement(element)

                if 'x1' in element:
                    rect = QRect(
                        int(element['x1'] * self.screen_label.scale_factor),
                        int(element['y1'] * self.screen_label.scale_factor),
                        int(element['width'] * self.screen_label.scale_factor),
                        int(element['height'] * self.screen_label.scale_factor)
                    )
                    self.screen_label.setClickRect(rect)
        
        if self.current_device and self.realtime_control_cb.isChecked():
            ADBHelper.tap(x, y, self.current_device)
            
            if self.auto_refresh:
                QTimer.singleShot(500, self.refreshScreen)
    
    def expandToElement(self, element):
        """展开到指定元素并选中"""
        element_id = id(element)
        if element_id in self.tree_items_map:
            tree_item = self.tree_items_map[element_id]
            
            self.hierarchy_tree.clearSelection()
            
            root = self.hierarchy_tree.invisibleRootItem()
            for i in range(root.childCount()):
                self.collapseAllChildren(root.child(i))
            
            path_to_expand = []
            current = tree_item
            while current:
                path_to_expand.append(current)
                current = current.parent()
            
            for node in reversed(path_to_expand):
                if node.parent():
                    node.parent().setExpanded(True)
            
            if tree_item.childCount() > 0:
                tree_item.setExpanded(True)
                last_child = tree_item.child(tree_item.childCount() - 1)
                last_child.setSelected(True)
                self.hierarchy_tree.scrollToItem(last_child, QAbstractItemView.PositionAtCenter)
            else:
                tree_item.setSelected(True)
                self.hierarchy_tree.scrollToItem(tree_item, QAbstractItemView.PositionAtCenter)

    def collapseAllChildren(self, item):
        """递归折叠所有子节点"""
        item.setExpanded(False)
        for i in range(item.childCount()):
            self.collapseAllChildren(item.child(i))
    
    def displayElementInfo(self, element):
        """显示元素信息"""
        self.info_table.setRowCount(0)
        
        properties = [
            ('Class', 'class'),
            ('ID', 'resource-id'),
            ('Text', 'text'),
            ('Content-Desc', 'content-desc'),
            ('Bounds', 'bounds'),
            ('Size', None),
            ('Clickable', 'clickable'),
            ('Enabled', 'enabled'),
            ('Focusable', 'focusable'),
            ('Scrollable', 'scrollable'),
            ('Package', 'package'),
            ('Index', 'index'),
            ('Text Source', 'text_source'),
            ('Info Supplemented', 'info_supplemented'),
        ]
        
        for prop_name, prop_key in properties:
            if prop_key:
                value = element.get(prop_key, '')
            elif prop_name == 'Size' and 'width' in element:
                value = f"{element['width']} x {element['height']}"
            else:
                continue
                
            if value or value == False:  # 包括布尔值False
                row = self.info_table.rowCount()
                self.info_table.insertRow(row)
                self.info_table.setItem(row, 0, QTableWidgetItem(prop_name))
                
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                
                # 特殊标记
                if prop_name == 'Content-Desc' and value:
                    item.setBackground(QBrush(QColor(220, 255, 220)))
                elif prop_name == 'Text' and value:
                    item.setBackground(QBrush(QColor(220, 240, 255)))
                elif prop_name == 'Text Source' and value:
                    item.setForeground(QBrush(QColor(100, 100, 100)))
                elif prop_name == 'Info Supplemented' and str(value) == 'True':
                    item.setForeground(QBrush(QColor(0, 150, 0)))
                
                self.info_table.setItem(row, 1, item)
    
    def updateHierarchyTree(self):
        """更新层级树"""
        self.hierarchy_tree.clear()
        self.tree_items_map.clear()
        
        if self.hierarchy_data:
            root_item = QTreeWidgetItem(self.hierarchy_tree)
            self._buildTreeItem(root_item, self.hierarchy_data)
            self.hierarchy_tree.expandToDepth(2)
    
    def _buildTreeItem(self, parent_item, node_data):
        """构建树节点"""
        class_name = node_data.get('class', '').split('.')[-1]
        text = node_data.get('text', '')
        content_desc = node_data.get('content-desc', '')
        resource_id = node_data.get('resource-id', '').split('/')[-1] if node_data.get('resource-id') else ''
        
        display_text = class_name
        if resource_id:
            display_text += f" [{resource_id}]"
        
        # 优先显示content-desc，其次是text
        if content_desc:
            display_text += f" - {content_desc[:30]}"
        elif text:
            display_text += f" - {text[:30]}"
        
        parent_item.setText(0, display_text)
        parent_item.setData(0, Qt.UserRole, node_data)
        
        self.tree_items_map[id(node_data)] = parent_item
        
        # 根据内容设置颜色
        if content_desc or text:
            parent_item.setForeground(0, QBrush(QColor(0, 150, 0)))
        elif 'Button' in class_name:
            parent_item.setForeground(0, QBrush(QColor(0, 122, 204)))
        elif 'Text' in class_name:
            parent_item.setForeground(0, QBrush(QColor(52, 152, 219)))
        elif 'Image' in class_name:
            parent_item.setForeground(0, QBrush(QColor(46, 204, 113)))
        
        for child in node_data.get('children', []):
            child_item = QTreeWidgetItem(parent_item)
            self._buildTreeItem(child_item, child)
    
    def onTreeItemClicked(self, item, column):
        """处理树节点点击"""
        node_data = item.data(0, Qt.UserRole)
        if node_data:
            self.displayElementInfo(node_data)
            
            if 'x1' in node_data:
                rect = QRect(
                    int(node_data['x1'] * self.screen_label.scale_factor),
                    int(node_data['y1'] * self.screen_label.scale_factor),
                    int(node_data['width'] * self.screen_label.scale_factor),
                    int(node_data['height'] * self.screen_label.scale_factor)
                )
                self.screen_label.setClickRect(rect)
    
    def searchElement(self):
        """搜索元素"""
        search_text = self.search_input.text().lower()
        if not search_text or not self.hierarchy_data:
            return
        
        results = []
        self._searchInNode(self.hierarchy_data, search_text, results)
        
        if results:
            self.displayElementInfo(results[0])
            self.expandToElement(results[0])
            self.status_bar.showMessage(f"找到 {len(results)} 个匹配项")
        else:
            self.status_bar.showMessage("未找到匹配的元素")
    
    def _searchInNode(self, node, search_text, results):
        """递归搜索节点"""
        if (search_text in node.get('resource-id', '').lower() or
            search_text in node.get('text', '').lower() or
            search_text in node.get('class', '').lower() or
            search_text in node.get('content-desc', '').lower()):
            results.append(node)
        
        for child in node.get('children', []):
            self._searchInNode(child, search_text, results)

def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = CarScreenMirrorTool()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
