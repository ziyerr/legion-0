#!/usr/bin/env python3
"""
从 agency-agents 加载 146+ 个专家档案

功能：
1. 扫描所有专家目录（每个目录一个专家）
2. 读取 AGENTS.md 人格定义文件
3. 转换为 AgentProfile 格式
4. 支持按领域筛选

安全加固：
- 路径遍历防护
- 输入验证
- 安全的日志记录

作者：Krislu
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AgentProfile:
    """Agent 档案（从 Markdown 文件加载）"""
    agent_id: str
    name: str
    description: str
    category: str
    content: str
    file_path: str


class AgencyAgentsLoader:
    """agency-agents 加载器（安全加固版）"""
    
    def __init__(self, base_path: str = None):
        """
        初始化加载器
        
        Args:
            base_path: agency-agents 基础路径
            
        默认路径优先级：
        1. 传入的 base_path 参数
        2. 环境变量 AGENCY_AGENTS_PATH（需验证）
        3. 默认路径（相对于当前文件）
        """
        if base_path is None:
            env_path = os.environ.get("AGENCY_AGENTS_PATH")
            if env_path:
                if self._is_safe_path(env_path):
                    base_path = env_path
                else:
                    logger.warning(f"AGENCY_AGENTS_PATH 路径不安全，使用默认路径")
            
            if base_path is None:
                # 支持两种目录名：agency-agents 或 agency-agents
                for dirname in ["agency-agents", "agency-agents"]:
                    test_path = os.path.join(os.path.dirname(__file__), dirname)
                    if os.path.exists(test_path):
                        base_path = test_path
                        break
                
                if base_path is None:
                    base_path = os.path.join(os.path.dirname(__file__), "agency-agents")
        
        self.base_path = Path(base_path).resolve()
        
        if not self._is_safe_path(str(self.base_path)):
            raise ValueError(f"不安全的 base_path: {self.base_path}")
        
        self.agents: Dict[str, AgentProfile] = {}
        self.categories: Dict[str, List[str]] = {}
    
    def _is_safe_path(self, path: str) -> bool:
        """
        验证路径是否安全
        
        安全标准：
        1. 必须在技能目录内
        2. 不允许访问系统敏感目录
        3. 不允许符号链接跳出目录
        """
        try:
            real_path = os.path.realpath(path)
            skill_dir = os.path.realpath(os.path.dirname(__file__))
            
            # 必须位于技能目录内
            if not real_path.startswith(skill_dir):
                logger.warning(f"路径不在技能目录内：{real_path}")
                return False
            
            # 禁止访问敏感目录
            forbidden = ['/etc', '/proc', '/sys', '/root']
            if any(real_path.startswith(p) for p in forbidden):
                return False
            
            return True
        except Exception as e:
            logger.error(f"路径验证失败：{e}")
            return False
    
    def load_all(self) -> Dict[str, AgentProfile]:
        """加载所有专家档案（安全加固）
        
        专家库结构：
        agency-agents/
        ├── engineering-ai-engineer/    # 专家目录（agent_id）
        │   ├── AGENTS.md               # 人格定义文件（必须）
        │   ├── IDENTITY.md
        │   ├── SOUL.md
        │   └── ...
        ├── marketing-xiaohongshu-operator/
        │   └── AGENTS.md
        └── ...
        
        每个专家目录 = 一个专家，AGENTS.md = 人格定义
        """
        logger.info(f"从 {self.base_path} 加载专家档案...")
        
        if not self.base_path.exists():
            logger.error(f"专家目录不存在：{self.base_path}")
            return {}
        
        if not self.base_path.is_dir():
            logger.error(f"专家目录不是目录：{self.base_path}")
            return {}
        
        agent_dirs = []
        
        # 扫描一级子目录（每个目录是一个专家）
        for item in self.base_path.iterdir():
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    agent_dirs.append(item)
            except Exception as e:
                logger.warning(f"扫描目录失败 {item}: {e}")
        
        logger.info(f"找到 {len(agent_dirs)} 个专家目录")
        
        for agent_dir in agent_dirs:
            try:
                # 每个专家目录中读取 AGENTS.md
                agents_file = agent_dir / "AGENTS.md"
                if agents_file.exists():
                    agent = self._load_agent_file(agents_file)
                    if agent:
                        self.agents[agent.agent_id] = agent
                        if agent.category not in self.categories:
                            self.categories[agent.category] = []
                        self.categories[agent.category].append(agent.agent_id)
                else:
                    logger.warning(f"专家目录缺少 AGENTS.md: {agent_dir}")
            except Exception as e:
                logger.error(f"加载失败 {agent_dir}: {type(e).__name__}")
        
        logger.info(f"成功加载 {len(self.agents)} 个专家")
        return self.agents
    
    def _should_exclude(self, file_path: Path) -> bool:
        """判断文件是否应该排除"""
        exclude_files = [
            "README.md", "CONTRIBUTING.md", "UPSTREAM.md",
            "QUICKSTART.md", "EXECUTIVE-BRIEF.md"
        ]
        exclude_dirs = ["strategy", "coordination", "playbooks", "runbooks"]
        
        if file_path.name in exclude_files:
            return True
        
        if file_path.parent.name in exclude_dirs:
            return True
        
        if "strategy" in str(file_path.parent):
            return True
        
        return False
    
    def _load_agent_file(self, file_path: Path) -> Optional[AgentProfile]:
        """加载单个专家文件（安全加固）
        
        AGENTS.md 格式：
        # AI 工程师
        你是**AI 工程师**，一位在模型开发和工程化落地之间架桥的实战派...
        
        从标题提取 name，从目录名提取 agent_id 和 category
        """
        try:
            file_size = file_path.stat().st_size
            if file_size > 10 * 1024 * 1024:  # 10MB 限制
                logger.warning(f"文件过大，跳过：{file_path} ({file_size} bytes)")
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 从目录名获取 agent_id（如 engineering-ai-engineer）
            agent_id = file_path.parent.name
            
            # 从目录名提取 category（如 engineering）
            category = agent_id.split('-')[0] if '-' in agent_id else agent_id
            
            # 从 Markdown 标题提取专家名称（如 "AI 工程师"）
            name = self._extract_name_from_markdown(content, agent_id)
            
            # 提取简短描述（第一段或前 200 字符）
            description = self._extract_description(content)
            
            return AgentProfile(
                agent_id=agent_id,
                name=name,
                description=description,
                category=category,
                content=content,
                file_path=str(file_path)
            )
        except Exception as e:
            logger.error(f"读取文件失败 {file_path}: {type(e).__name__}")
            return None
    
    def _extract_name_from_markdown(self, content: str, default: str) -> str:
        """从 Markdown 内容提取专家名称"""
        # 尝试从第一行标题提取
        match = re.match(r'^#\s+(.+)$', content.strip(), re.MULTILINE)
        if match:
            return match.group(1).strip()
        
        # 尝试从目录名转换（engineering-ai-engineer → AI Engineer）
        return default.replace('-', ' ').title()
    
    def _extract_description(self, content: str) -> str:
        """提取简短描述（第一段或前 200 字符）"""
        # 移除标题
        content_without_title = re.sub(r'^#\s+.+$\n', '', content, flags=re.MULTILINE)
        
        # 提取第一段
        paragraphs = content_without_title.strip().split('\n\n')
        if paragraphs:
            first_para = paragraphs[0].strip()
            # 限制长度
            if len(first_para) > 200:
                return first_para[:200] + '...'
            return first_para
        
        return content[:200] + '...' if len(content) > 200 else content
    
    def _parse_frontmatter(self, content: str) -> Optional[Dict]:
        """解析 Markdown frontmatter"""
        match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
        if not match:
            return None
        
        frontmatter_text = match.group(1)
        frontmatter = {}
        
        for line in frontmatter_text.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                frontmatter[key.strip()] = value.strip()
        
        return frontmatter
    
    def get_agents_by_category(self, category: str) -> List[AgentProfile]:
        """按分类获取专家"""
        agent_ids = self.categories.get(category, [])
        return [self.agents[aid] for aid in agent_ids if aid in self.agents]
    
    def get_agents_by_keywords(self, keywords: List[str]) -> List[AgentProfile]:
        """按关键词匹配专家"""
        if not keywords:
            return []
        
        matched = []
        for agent in self.agents.values():
            search_text = f"{agent.name} {agent.description} {agent.category}".lower()
            if any(kw.lower() in search_text for kw in keywords):
                matched.append(agent)
        return matched
    
    def get_expert_prompt(self, agent_id: str, topic: str, focus: Dict) -> str:
        """生成专家提示词"""
        agent = self.agents.get(agent_id)
        if not agent:
            return ""
        
        content = re.sub(r'^---\n.*?\n---\n', '', agent.content, flags=re.DOTALL)
        safe_topic = topic[:500] if topic else "未知主题"
        
        prompt = f"""{content}

## 当前讨论主题
**{safe_topic}**

## 你的专业领域
{agent.description}

## 当前议题
**{focus.get('name', '未知')}**

## 焦点问题
{chr(10).join(['- ' + q for q in focus.get('focus_questions', [])])}

---

## 你的任务
请从你的专业角度，对当前议题进行深度分析。

### 必须包含的内容
1. **专业分析**（400 字以上）
2. **实施建议**（200 字以上）

请开始你的专业分析：
"""
        return prompt
    
    def list_all_agents(self) -> str:
        """列出所有专家"""
        lines = ["# 170 个专家完整列表\n"]
        for category, agent_ids in sorted(self.categories.items()):
            lines.append(f"\n## {category}\n")
            for agent_id in agent_ids:
                agent = self.agents.get(agent_id)
                if agent:
                    lines.append(f"- **{agent.name}** (`{agent_id}`) - {agent.description}")
        return "\n".join(lines)


def load_all_agents() -> Dict[str, AgentProfile]:
    """快捷函数：加载所有专家"""
    loader = AgencyAgentsLoader()
    return loader.load_all()


def get_agents_for_topic(topic: str) -> List[AgentProfile]:
    """快捷函数：根据主题获取相关专家"""
    loader = AgencyAgentsLoader()
    loader.load_all()
    keywords = topic.split()
    return loader.get_agents_by_keywords(keywords)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loader = AgencyAgentsLoader()
    agents = loader.load_all()
    print(f"\n📊 统计信息：")
    print(f"  总专家数：{len(agents)}")
    print(f"  分类数：{len(loader.categories)}")
