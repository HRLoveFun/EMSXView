#!/usr/bin/env python3
"""
工程准则评估框架 (Engineering Guideline Evaluation Framework)
==============================================================

基于 engineering_guideline.md 中定义的全部评估项目，对代码项目进行结构化、
量化的质量评估。支持手动评分与部分自动化检测，输出清晰的结构化报告。

用法:
    python engineering_evaluation.py                          # 交互式评估
    python engineering_evaluation.py --auto <项目路径>         # 自动化检测+评估
    python engineering_evaluation.py --list                   # 列出所有评估项目
    python engineering_evaluation.py --report <json路径>       # 从已有评分生成报告
"""

import abc
import json
import os
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  第一部分：评估准则定义                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class SubCriterion:
    """单个子准则"""
    id: str                             # 唯一标识符，如 "MOD-01"
    name: str                           # 名称
    description: str                    # 详细描述（取自工程准则文档）
    weight: float = 1.0                 # 在该项目内的权重
    scoring_guide: Dict[int, str] = field(default_factory=lambda: {
        1: "完全不满足 — 没有相关实践，甚至存在反模式",
        2: "部分满足 — 有意识但执行不连贯，多处待改进",
        3: "基本满足 — 大多数场景下符合要求，偶有疏漏",
        4: "较好满足 — 系统性实践，仅少数细节可优化",
        5: "完全满足 — 最佳实践水平，可作为标杆",
    })
    # 可选的自动化检测函数：输入项目路径，返回 (分数, 证据)
    auto_check: Optional[Callable[[str], Tuple[int, str]]] = None


@dataclass
class EvaluationItem:
    """评估项目（对应 engineering_guideline 中的一个核心概念）"""
    id: str                             # 唯一标识符，如 "C01"
    name: str                           # 中文名
    name_en: str                        # 英文名
    category: str                       # 所属类别
    chapter: str                        # 所属章节
    description: str                    # 准则说明
    weight: float                       # 在总评估中的权重
    sub_criteria: List[SubCriterion]    # 子准则列表
    key_question: str                   # 核心判断问题


@dataclass
class EvaluationCategory:
    """评估类别"""
    id: str
    name: str
    name_en: str
    weight: float          # 在总评估中的权重
    description: str
    items: List[EvaluationItem]


# ═══════════════════════════════════════════════════════════════════════════════
#  定义全部评估项目
# ═══════════════════════════════════════════════════════════════════════════════

def _build_categories() -> List[EvaluationCategory]:
    """构建完整的评估类别与项目体系（基于 engineering_guideline.md）"""

    # ==========================================================================
    # 类别 A：复杂度管理（权重 20%）
    # ==========================================================================

    cat_a_items = [
        EvaluationItem(
            id="A01", name="模块化", name_en="Modularity",
            category="复杂度管理", chapter="1.1",
            description=(
                "把大系统拆成可以独立理解的小块。每个块（模块）是一个有明确边界的「零件」。"
                "好的模块化：每个模块职责单一、边界清晰、修改不影响其他模块。"
            ),
            weight=0.25,
            key_question="项目是否按职责拆分为边界清晰的模块？",
            sub_criteria=[
                SubCriterion("A01-01", "模块边界清晰度",
                             "每个模块有明确的边界，不把不相干的功能堆在一起"),
                SubCriterion("A01-02", "模块职责单一性",
                             "每个模块只做一件事，可以用一句话说清楚自己的职责"),
                SubCriterion("A01-03", "模块拆分合理性",
                             "模块粒度适中，不太大也不太小，符合业务自然边界"),
                SubCriterion("A01-04", "模块独立可理解性",
                             "可以在不了解其他模块的情况下理解单个模块"),
                SubCriterion("A01-05", "命名自解释性",
                             "模块名准确反映其职责，不产生歧义"),
            ]),
        EvaluationItem(
            id="A02", name="抽象", name_en="Abstraction",
            category="复杂度管理", chapter="1.2",
            description=(
                "忽略细节，只关注'做什么'，不关注'怎么做'。"
                "抽象是分层的，每一层只关心相邻层，业务层不需要知道 SQL 长什么样。"
            ),
            weight=0.25,
            key_question="高层代码是否隐藏了底层实现细节？",
            sub_criteria=[
                SubCriterion("A02-01", "抽象层次合理性",
                             "抽象层次划分合理，业务逻辑与基础设施分离"),
                SubCriterion("A02-02", "细节隐藏度",
                             "高层代码不泄露底层实现细节（如 SQL、API 调用方式）"),
                SubCriterion("A02-03", "抽象接口稳定性",
                             "抽象接口稳定，不随实现细节频繁变化"),
                SubCriterion("A02-04", "分层调用合规性",
                             "调用关系遵循抽象层次，不跨层越级调用"),
                SubCriterion("A02-05", "抽象命名准确性",
                             "抽象命名反映'做什么'而非'怎么做'"),
            ]),
        EvaluationItem(
            id="A03", name="封装", name_en="Encapsulation",
            category="复杂度管理", chapter="1.3",
            description=(
                "把数据和操作数据的方法捆绑在一起，并隐藏内部细节。"
                "封装 = 抽象 + 保护：对外简化，对内保护不变量。"
            ),
            weight=0.25,
            key_question="对象的内部数据和实现细节是否受到保护？",
            sub_criteria=[
                SubCriterion("A03-01", "内部数据保护",
                             "私有数据不暴露给外部直接读写（使用 _ 前缀或语言机制）"),
                SubCriterion("A03-02", "公共方法完整性",
                             "外部通过受控的公共方法操作对象，而非直接修改字段"),
                SubCriterion("A03-03", "不变量保护机制",
                             "通过方法确保数据状态始终合法（如数量 ≥ 0 的校验）"),
                SubCriterion("A03-04", "内部细节隐藏度",
                             "外部不依赖内部实现细节，内部改动不影响调用方"),
                SubCriterion("A03-05", "状态访问受控性",
                             "对象状态修改有明确的入口和校验逻辑"),
            ]),
        EvaluationItem(
            id="A04", name="内聚", name_en="Cohesion",
            category="复杂度管理", chapter="1.4",
            description=(
                "一个模块内部的元素是否'属于同一件事'。"
                "高内聚的模块容易理解、容易测试、容易复用。"
                "低内聚的模块是 bug 温床。"
            ),
            weight=0.25,
            key_question="模块内部元素是否紧密围绕同一职责？",
            sub_criteria=[
                SubCriterion("A04-01", "功能内聚程度",
                             "模块内部所有代码服务于同一功能目标"),
                SubCriterion("A04-02", "低内聚信号检测",
                             "没有出现'和''以及''顺便'等描述职责混杂的情况"),
                SubCriterion("A04-03", "代码组织合理性",
                             "相关代码放在一起，不相关代码分离"),
                SubCriterion("A04-04", "模块可独立测试性",
                             "模块可以独立测试，不需要大量外部准备"),
                SubCriterion("A04-05", "utils/misc 模块控制",
                             "没有'杂项'模块或其中的内容有明显归属"),
            ]),
    ]

    # ==========================================================================
    # 类别 B：协作机制（权重 25%）
    # ==========================================================================

    cat_b_items = [
        EvaluationItem(
            id="B01", name="接口", name_en="Interface",
            category="协作机制", chapter="2.1",
            description=(
                "模块对外承诺的'使用方式'——别人怎么调用我。"
                "核心智慧：依赖接口，不依赖实现。"
                "语法接口（签名）+ 语义接口（行为约定）同等重要。"
            ),
            weight=0.25,
            key_question="模块之间的调用是否通过清晰稳定的接口进行？",
            sub_criteria=[
                SubCriterion("B01-01", "语法接口清晰度",
                             "函数/方法签名清晰，类型注解完整，参数命名自解释"),
                SubCriterion("B01-02", "语义接口完备性",
                             "有文档/注释说明行为约定（前置条件、后置条件、边界情况）"),
                SubCriterion("B01-03", "接口契约明确性",
                             "接口明确承诺输入输出格式和异常行为"),
                SubCriterion("B01-04", "接口稳定性",
                             "接口不频繁变动，变动时对调用方透明"),
                SubCriterion("B01-05", "抽象基类/协议使用",
                             "使用 abc.ABC 或 Protocol 等机制定义接口契约"),
            ]),
        EvaluationItem(
            id="B02", name="依赖", name_en="Dependency",
            category="协作机制", chapter="2.2",
            description=(
                "A 需要 B 才能工作，就说 A 依赖 B。"
                "好的依赖图像树（DAG），没有循环。底层是基础设施，顶层是业务逻辑。"
                "循环依赖是灾难，必须立刻重构。"
            ),
            weight=0.25,
            key_question="依赖关系是否清晰、无循环、方向合理？",
            sub_criteria=[
                SubCriterion("B02-01", "无循环依赖",
                             "模块间没有 A→B→C→A 的循环依赖"),
                SubCriterion("B02-02", "依赖方向合理性",
                             "高层依赖低层（业务→基础设施），而非反向"),
                SubCriterion("B02-03", "依赖图层次清晰",
                             "依赖关系呈有向无环图（DAG），层次分明"),
                SubCriterion("B02-04", "依赖数量可控",
                             "单个模块的依赖数量合理，不过度依赖其他模块"),
                SubCriterion("B02-05", "外部依赖隔离",
                             "外部库/服务的依赖有抽象层隔离，便于替换"),
            ]),
        EvaluationItem(
            id="B03", name="耦合", name_en="Coupling",
            category="协作机制", chapter="2.3",
            description=(
                "模块之间互相牵连的紧密程度。"
                "追求'数据耦合'以下，避免'公共耦合'以上。"
                "高内聚、低耦合是软件工程最重要的一条法则。"
            ),
            weight=0.25,
            key_question="模块之间的连接是否松散，改动一个不影响其他？",
            sub_criteria=[
                SubCriterion("B03-01", "耦合等级控制",
                             "没有内容耦合（改内部数据）和公共耦合（共享全局变量）"),
                SubCriterion("B03-02", "全局变量控制",
                             "不使用或极少使用全局可变状态"),
                SubCriterion("B03-03", "数据耦合优先",
                             "模块间主要通过数据传递而非控制参数通信"),
                SubCriterion("B03-04", "模块通信规范性",
                             "模块间通过接口/消息通信，不直接操作对方内部"),
                SubCriterion("B03-05", "修改影响范围",
                             "修改一个模块不需要连带修改多个其他模块"),
            ]),
        EvaluationItem(
            id="B04", name="错误边界", name_en="Error Boundary",
            category="协作机制", chapter="2.4",
            description=(
                "明确划定'哪里负责处理哪种错误'的边界。"
                "在系统自然边界上设防：入口、跨层调用、跨进程调用、跨子系统调用。"
                "三个策略：让它崩、捕获并转换、捕获并恢复。"
            ),
            weight=0.25,
            key_question="错误是否在合适的边界被捕获和处理，不影响全局？",
            sub_criteria=[
                SubCriterion("B04-01", "错误边界位置合理",
                             "在自然边界（入口、跨层调用）设有错误捕获"),
                SubCriterion("B04-02", "异常捕获策略恰当",
                             "根据场景选择正确的策略（崩/转换/恢复）"),
                SubCriterion("B04-03", "错误传播清晰",
                             "底层异常转换为业务异常，上层能理解错误含义"),
                SubCriterion("B04-04", "容错机制",
                             "单点失败不会导致整个进程崩溃（批量处理跳过失败项）"),
                SubCriterion("B04-05", "错误日志上下文完整",
                             "错误日志包含足够的上下文信息用于排查"),
            ]),
    ]

    # ==========================================================================
    # 类别 C：架构韧性（权重 25%）
    # ==========================================================================

    cat_c_items = [
        EvaluationItem(
            id="C01", name="单一职责原则", name_en="Single Responsibility Principle (SRP)",
            category="架构韧性", chapter="3.1",
            description=(
                "一个模块/类/函数只应该有一个'变化的理由'。"
                "如果某个类有多个变化理由，拆分为多个类。"
            ),
            weight=0.25,
            key_question="每个模块/类是否只有一个修改理由？",
            sub_criteria=[
                SubCriterion("C01-01", "职责数量控制",
                             "每个类/模块的职责可以用一句话说清"),
                SubCriterion("C01-02", "变化理由唯一性",
                             "不同原因的变化不会落在同一个类/模块上"),
                SubCriterion("C01-03", "函数长度控制",
                             "函数长度适中，不做多件事（单一函数单一操作）"),
                SubCriterion("C01-04", "职责混合检测",
                             "没有业务逻辑+持久化+通知混合在同一个类中"),
                SubCriterion("C01-05", "拆分合理度",
                             "拆分后的类职责明确、粒度适中、协作清晰"),
            ]),
        EvaluationItem(
            id="C02", name="开闭原则", name_en="Open-Closed Principle (OCP)",
            category="架构韧性", chapter="3.2",
            description=(
                "对扩展开放，对修改关闭。加新功能时新写代码而不是改老代码。"
                "老代码不动 = 老 bug 不会被引入 + 老测试不用重跑。"
            ),
            weight=0.25,
            key_question="新增功能时是否需要修改已有代码？",
            sub_criteria=[
                SubCriterion("C02-01", "扩展机制设计",
                             "系统提供了扩展点，新增功能不需要大改现有代码"),
                SubCriterion("C02-02", "抽象基类/接口扩展",
                             "通过实现接口/继承抽象类来扩展功能"),
                SubCriterion("C02-03", "新增不改旧",
                             "过去一个月新增的功能没有修改已有稳定代码"),
                SubCriterion("C02-04", "策略/插件模式运用",
                             "变化点使用策略模式、插件架构等设计模式处理"),
                SubCriterion("C02-05", "修改封闭性",
                             "核心调度/编排逻辑对扩展封闭（不需随功能增加而修改）"),
            ]),
        EvaluationItem(
            id="C03", name="依赖倒置", name_en="Dependency Inversion Principle (DIP)",
            category="架构韧性", chapter="3.3",
            description=(
                "高层模块不应该依赖低层模块的具体实现，两者都应该依赖抽象（接口）。"
                "好处：可测试（传 Mock）、可替换（换实现不动业务代码）、解耦。"
            ),
            weight=0.25,
            key_question="高层业务代码是依赖抽象接口还是具体实现？",
            sub_criteria=[
                SubCriterion("C03-01", "高层依赖抽象",
                             "高层模块不直接依赖低层具体实现，通过抽象接口依赖"),
                SubCriterion("C03-02", "可替换性",
                             "低层实现可替换（如数据库切换）而不影响上层"),
                SubCriterion("C03-03", "测试友好性",
                             "可通过 Mock/Stub 替换真实依赖进行测试"),
                SubCriterion("C03-04", "依赖注入使用",
                             "依赖通过构造函数/方法参数注入，而非内部创建"),
                SubCriterion("C03-05", "抽象接口稳定",
                             "抽象接口不依赖于具体实现的细节"),
            ]),
        EvaluationItem(
            id="C04", name="关注点分离", name_en="Separation of Concerns (SoC)",
            category="架构韧性", chapter="3.4",
            description=(
                "不同性质的逻辑写在不同地方：业务逻辑、数据持久化、表现层、基础设施。"
                "上层可以依赖下层，下层不能依赖上层，同层尽量不依赖。"
            ),
            weight=0.25,
            key_question="不同关注点（业务/数据/展示/基础设施）是否分离？",
            sub_criteria=[
                SubCriterion("C04-01", "分层架构清晰",
                             "项目有明确的分层（入口、业务编排、业务逻辑、数据访问、基础设施）"),
                SubCriterion("C04-02", "各层职责明确",
                             "每层职责定义清楚，不越界处理其他层的事务"),
                SubCriterion("C04-03", "跨层调用规范",
                             "上层只调用相邻下层，不跨层直接调用"),
                SubCriterion("C04-04", "关注点不混合",
                             "业务逻辑中不混入 SQL/IO/UI 代码"),
                SubCriterion("C04-05", "基础设施隔离",
                             "数据库、网络、文件系统等基础设施有独立层封装"),
            ]),
    ]

    # ==========================================================================
    # 类别 D：质量保障（权重 15%）
    # ==========================================================================

    cat_d_items = [
        EvaluationItem(
            id="D01", name="测试策略", name_en="Testing Strategy",
            category="质量保障", chapter="4.1",
            description=(
                "测试金字塔：70% 单元测试 + 25% 集成测试 + 5% E2E。"
                "单元测试快（毫秒级）、多、稳定；集成测试捕获模块协作 bug。"
            ),
            weight=0.40,
            key_question="测试分布是否遵循金字塔原则？",
            sub_criteria=[
                SubCriterion("D01-01", "测试覆盖率",
                             "关键业务逻辑有单元测试覆盖"),
                SubCriterion("D01-02", "测试金字塔比例",
                             "测试分布合理：单元测试多于集成测试多于 E2E"),
                SubCriterion("D01-03", "测试独立性",
                             "测试之间不相互依赖，可以独立运行"),
                SubCriterion("D01-04", "测试可维护性",
                             "测试代码简洁、易读，不因实现变更频繁失效"),
            ]),
        EvaluationItem(
            id="D02", name="不变量保护", name_en="Invariant Protection",
            category="质量保障", chapter="4.2",
            description=(
                "系统在任何时候都必须为真的命题。"
                "所有 bug 本质都是某个不变量被破坏了。"
                "不变量应写在代码里（断言）和测试里。"
            ),
            weight=0.30,
            key_question="关键不变量是否有断言或测试保护？",
            sub_criteria=[
                SubCriterion("D02-01", "关键不变量识别",
                             "项目中识别并记录了关键不变量"),
                SubCriterion("D02-02", "断言使用",
                             "代码中使用 assert 保护关键不变量"),
                SubCriterion("D02-03", "不变量测试",
                             "测试中包含不变量检查（如聚合后总量不变）"),
                SubCriterion("D02-04", "不变量文档化",
                             "不变量在接口文档或代码注释中有记录"),
            ]),
        EvaluationItem(
            id="D03", name="副作用管理", name_en="Side Effect Management",
            category="质量保障", chapter="4.3",
            description=(
                "函数除了返回值以外对外界产生的影响。"
                "尽量让函数纯，必须有副作用时集中在少数模块里且显式标明。"
            ),
            weight=0.30,
            key_question="副作用是否被显式管理和集中控制？",
            sub_criteria=[
                SubCriterion("D03-01", "纯函数优先",
                             "纯计算逻辑尽量写成纯函数（无副作用）"),
                SubCriterion("D03-02", "副作用集中管理",
                             "数据库、网络、文件等副作用集中在 Repository/DAO 层"),
                SubCriterion("D03-03", "副作用显式化",
                             "函数名/文档标明是否有副作用，调用方可预期"),
            ]),
    ]

    # ==========================================================================
    # 类别 E：工程实践（权重 15%）
    # ==========================================================================

    cat_e_items = [
        EvaluationItem(
            id="E01", name="配置管理", name_en="Configuration Management",
            category="工程实践", chapter="5.1",
            description=(
                "把会变的参数（路径、阈值、开关）从代码里抽出来。"
                "换环境只改配置，不改代码。"
            ),
            weight=0.20,
            key_question="可变参数是否配置化，与环境分离？",
            sub_criteria=[
                SubCriterion("E01-01", "配置外部化",
                             "硬编码值少，路径/阈值/开关等从配置读"),
                SubCriterion("E01-02", "环境分离",
                             "开发/测试/生产环境使用不同配置"),
                SubCriterion("E01-03", "敏感信息安全",
                             "密码/token 等敏感信息不硬编码在代码中"),
            ]),
        EvaluationItem(
            id="E02", name="日志规范", name_en="Logging",
            category="工程实践", chapter="5.2",
            description=(
                "在代码运行时记录关键事件，供事后分析。"
                "不要用 print，用 logging 模块。"
                "INFO 记录做了什么，ERROR 记录出了什么问题。"
            ),
            weight=0.20,
            key_question="日志是否规范、有层次、便于排查问题？",
            sub_criteria=[
                SubCriterion("E02-01", "日志级别合理",
                             "使用 DEBUG/INFO/WARNING/ERROR 分级记录"),
                SubCriterion("E02-02", "日志内容有价值",
                             "INFO 记录关键操作，ERROR 有上下文可用于排查"),
                SubCriterion("E02-03", "无 print 残留",
                             "不使用 print 替代 logging"),
            ]),
        EvaluationItem(
            id="E03", name="异常处理", name_en="Exception Handling",
            category="工程实践", chapter="5.3",
            description=(
                "异常用于'不该发生但发生了'的情况，不用于正常控制流。"
                "跨层调用时把底层异常转换为上层能理解的语言。"
            ),
            weight=0.20,
            key_question="异常处理是否规范，不滥用不忽略？",
            sub_criteria=[
                SubCriterion("E03-01", "异常类型恰当",
                             "使用合适的异常类型，不统一抛 Exception"),
                SubCriterion("E03-02", "跨层异常转换",
                             "在层边界把底层异常转换为业务异常"),
                SubCriterion("E03-03", "异常不用于控制流",
                             "异常只处理异常情况，不用 try/except 做流程控制"),
            ]),
        EvaluationItem(
            id="E04", name="状态设计", name_en="State Design",
            category="工程实践", chapter="5.4",
            description=(
                "能无状态尽量无状态，可测试性、可并发性都好得多。"
                "有状态时状态管理要清晰、变化可追踪。"
            ),
            weight=0.20,
            key_question="状态是否被合理管理，无状态优先？",
            sub_criteria=[
                SubCriterion("E04-01", "无状态优先",
                             "工具类函数设计为无状态（纯函数优先）"),
                SubCriterion("E04-02", "状态管理清晰",
                             "有状态的对象状态变化路径清晰可追踪"),
                SubCriterion("E04-03", "并发安全性",
                             "有状态对象在并发场景下有保护机制"),
            ]),
        EvaluationItem(
            id="E05", name="幂等性设计", name_en="Idempotency",
            category="工程实践", chapter="5.6",
            description=(
                "操作执行 1 次和 N 次结果一样。"
                "网络不稳定时，重试操作必须幂等才安全。API 设计时优先做幂等。"
            ),
            weight=0.20,
            key_question="关键写入操作是否幂等，重试安全？",
            sub_criteria=[
                SubCriterion("E05-01", "关键操作幂等",
                             "写入/更新类操作设计为幂等"),
                SubCriterion("E05-02", "重试安全",
                             "网络抖动导致的重复执行不会产生数据错误"),
                SubCriterion("E05-03", "API 幂等设计",
                             "对外/对内 API 的写操作遵循幂等设计"),
            ]),
    ]

    categories = [
        EvaluationCategory(
            id="A", name="复杂度管理", name_en="Complexity Management",
            weight=0.20,
            description="怎么让大东西变小——模块化、抽象、封装、内聚",
            items=cat_a_items,
        ),
        EvaluationCategory(
            id="B", name="协作机制", name_en="Collaboration Mechanism",
            weight=0.25,
            description="分开的东西怎么协作——接口、依赖、耦合、错误边界",
            items=cat_b_items,
        ),
        EvaluationCategory(
            id="C", name="架构韧性", name_en="Architecture Resilience",
            weight=0.25,
            description="系统怎么活得久——SRP、OCP、DIP、SoC",
            items=cat_c_items,
        ),
        EvaluationCategory(
            id="D", name="质量保障", name_en="Quality Assurance",
            weight=0.15,
            description="怎么知道东西没坏——测试金字塔、不变量、副作用",
            items=cat_d_items,
        ),
        EvaluationCategory(
            id="E", name="工程实践", name_en="Engineering Practices",
            weight=0.15,
            description="常用工程规范——配置、日志、异常、状态、幂等性",
            items=cat_e_items,
        ),
    ]

    return categories


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  第二部分：评分引擎                                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class SubScore:
    """子准则评分记录"""
    criterion_id: str
    criterion_name: str
    score: int              # 1-5
    evidence: str           # 评分依据/证据
    weight: float = 1.0


@dataclass
class ItemScore:
    """评估项目评分汇总"""
    item_id: str
    item_name: str
    item_name_en: str
    weight: float
    sub_scores: List[SubScore]
    average_score: float = 0.0
    weighted_score: float = 0.0

    def compute(self) -> None:
        """计算加权平均分"""
        if not self.sub_scores:
            self.average_score = 0.0
            self.weighted_score = 0.0
            return
        total_weight = sum(s.weight for s in self.sub_scores)
        if total_weight == 0:
            self.average_score = 0.0
            self.weighted_score = 0.0
            return
        self.average_score = round(
            sum(s.score * s.weight for s in self.sub_scores) / total_weight, 2
        )
        # 项目得分是其平均分（后续在类别层再加权）
        self.weighted_score = self.average_score


@dataclass
class CategoryScore:
    """类别评分汇总"""
    category_id: str
    category_name: str
    category_name_en: str
    weight: float
    item_scores: List[ItemScore]
    average_score: float = 0.0
    weighted_score: float = 0.0

    def compute(self) -> None:
        """计算类别得分"""
        if not self.item_scores:
            self.average_score = 0.0
            self.weighted_score = 0.0
            return
        total_weight = sum(it.weight for it in self.item_scores)
        if total_weight == 0:
            self.average_score = 0.0
            self.weighted_score = 0.0
            return
        self.average_score = round(
            sum(it.weighted_score * it.weight for it in self.item_scores) / total_weight, 2
        )
        self.weighted_score = round(self.average_score * self.weight, 2)


@dataclass
class EvaluationResult:
    """完整评估结果"""
    project_name: str
    evaluator: str
    date: str
    categories: List[CategoryScore]
    total_score: float = 0.0
    max_score: float = 5.0

    def compute(self) -> None:
        """计算总分"""
        if not self.categories:
            self.total_score = 0.0
            return
        total_weight = sum(c.weight for c in self.categories)
        if total_weight == 0:
            self.total_score = 0.0
            return
        # 归一化权重
        self.total_score = round(
            sum(c.weighted_score for c in self.categories) / total_weight * 5.0, 2
        )

    def get_rating(self) -> Tuple[str, str]:
        """获取等级评价"""
        pct = self.total_score / self.max_score
        if pct >= 0.90:
            return "🌟 卓越 (Excellent)", "工程实践达到行业领先水平，可作为组织标杆。"
        elif pct >= 0.80:
            return "👍 良好 (Good)", "工程实践扎实，有少量可优化项。"
        elif pct >= 0.65:
            return "📈 合格 (Adequate)", "基本工程规范已建立，存有明确的改进空间。"
        elif pct >= 0.50:
            return "⚠️ 待改进 (Needs Improvement)", "工程实践存在系统性不足，建议制定改进计划。"
        else:
            return "🔴 薄弱 (Weak)", "工程基础薄弱，建议从核心规范开始系统性建设。"


class EvaluationEngine:
    """评估引擎——驱动评分过程"""

    def __init__(self, categories: List[EvaluationCategory]):
        self.categories = categories
        self._flat_items: Dict[str, EvaluationItem] = {}
        self._flat_subs: Dict[str, SubCriterion] = {}
        self._index()

    def _index(self) -> None:
        """建立快速索引"""
        for cat in self.categories:
            for item in cat.items:
                self._flat_items[item.id] = item
                for sub in item.sub_criteria:
                    self._flat_subs[sub.id] = sub

    def get_all_items(self) -> List[EvaluationItem]:
        """获取所有评估项目"""
        result = []
        for cat in self.categories:
            result.extend(cat.items)
        return result

    def get_item(self, item_id: str) -> Optional[EvaluationItem]:
        return self._flat_items.get(item_id)

    def get_sub(self, sub_id: str) -> Optional[SubCriterion]:
        return self._flat_subs.get(sub_id)

    def interactive_evaluate(self) -> EvaluationResult:
        """交互式评估：逐一询问用户评分"""
        print("\n" + "=" * 70)
        print("  📋 工程准则评估框架 — 交互式评估")
        print("=" * 70)
        print("\n评分标准：")
        for s, desc in sorted(SubCriterion().scoring_guide.items()):
            print(f"  {s}分 — {desc}")
        print("\n按 Ctrl+C 随时保存已完成的评分。\n")

        project_name = input("项目名称: ").strip() or "未命名项目"
        evaluator = input("评估人: ").strip() or "未知"

        category_scores = []

        for cat in self.categories:
            print(f"\n{'─' * 70}")
            print(f"  📁 [{cat.id}] {cat.name} ({cat.name_en})")
            print(f"  {cat.description}")
            print(f"  类别权重: {cat.weight * 100:.0f}%")
            print(f"{'─' * 70}")

            item_scores = []
            for item in cat.items:
                print(f"\n  ◆ {item.id} {item.name} ({item.name_en})")
                print(f"    核心问题: {item.key_question}")
                print(f"    项目权重: {item.weight * 100:.0f}%")

                sub_scores = []
                for sub in item.sub_criteria:
                    while True:
                        try:
                            raw = input(f"\n    [{sub.id}] {sub.name}: {sub.description[:60]}...\n      评分 (1-5): ").strip()
                            score = int(raw)
                            if 1 <= score <= 5:
                                break
                            print("      评分须在 1-5 之间，请重新输入。")
                        except (ValueError, EOFError):
                            print("      输入无效，请重新输入。")
                        except KeyboardInterrupt:
                            raise

                    evidence = input(f"      评分依据（可选）: ").strip()
                    sub_scores.append(SubScore(
                        criterion_id=sub.id,
                        criterion_name=sub.name,
                        score=score,
                        evidence=evidence or "(无记录)",
                        weight=sub.weight,
                    ))

                iscore = ItemScore(
                    item_id=item.id,
                    item_name=item.name,
                    item_name_en=item.name_en,
                    weight=item.weight,
                    sub_scores=sub_scores,
                )
                iscore.compute()
                item_scores.append(iscore)

                # 显示项目得分
                bar = _score_bar(iscore.average_score)
                print(f"    ──▶ {item.name} 得分: {iscore.average_score:.2f}/5.0 {bar}")

            cscore = CategoryScore(
                category_id=cat.id,
                category_name=cat.name,
                category_name_en=cat.name_en,
                weight=cat.weight,
                item_scores=item_scores,
            )
            cscore.compute()
            category_scores.append(cscore)

            # 显示类别得分
            bar = _score_bar(cscore.average_score)
            print(f"\n  ━━━━▶ [{cat.id}] {cat.name} 类别得分: {cscore.average_score:.2f}/5.0 {bar}")

        result = EvaluationResult(
            project_name=project_name,
            evaluator=evaluator,
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            categories=category_scores,
        )
        result.compute()
        return result

    def auto_evaluate(self, project_path: str) -> EvaluationResult:
        """自动化评估：运行可自动化检测的准则，其余标记为待人工评分"""
        project_name = os.path.basename(os.path.abspath(project_path))

        category_scores = []

        for cat in self.categories:
            item_scores = []
            for item in cat.items:
                sub_scores = []
                for sub in item.sub_criteria:
                    if sub.auto_check:
                        try:
                            score, evidence = sub.auto_check(project_path)
                        except Exception as e:
                            score, evidence = 0, f"自动检测失败: {e}"
                    else:
                        score, evidence = 0, "需人工评分"

                    sub_scores.append(SubScore(
                        criterion_id=sub.id,
                        criterion_name=sub.name,
                        score=score,
                        evidence=evidence,
                        weight=sub.weight,
                    ))

                iscore = ItemScore(
                    item_id=item.id,
                    item_name=item.name,
                    item_name_en=item.name_en,
                    weight=item.weight,
                    sub_scores=sub_scores,
                )
                iscore.compute()
                item_scores.append(iscore)

            cscore = CategoryScore(
                category_id=cat.id,
                category_name=cat.name,
                category_name_en=cat.name_en,
                weight=cat.weight,
                item_scores=item_scores,
            )
            cscore.compute()
            category_scores.append(cscore)

        result = EvaluationResult(
            project_name=project_name,
            evaluator="自动检测引擎",
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            categories=category_scores,
        )
        result.compute()
        return result


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  第三部分：报告生成器                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def _score_bar(score: float, max_score: float = 5.0, width: int = 20) -> str:
    """生成可视化分数条"""
    filled = int(round(score / max_score * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}]"


def _color_for_score(score: float, max_score: float = 5.0) -> str:
    """根据分数返回颜色标签"""
    pct = score / max_score
    if pct >= 0.9:
        return "🟢"  # 绿
    elif pct >= 0.7:
        return "🔵"  # 蓝
    elif pct >= 0.5:
        return "🟡"  # 黄
    else:
        return "🔴"  # 红


def generate_markdown_report(result: EvaluationResult) -> str:
    """生成 Markdown 格式的结构化评估报告"""
    lines = []
    rating, rating_desc = result.get_rating()

    # 标题
    lines.append(f"# 📊 工程准则评估报告")
    lines.append("")
    lines.append(f"**项目**: {result.project_name}  ")
    lines.append(f"**评估人**: {result.evaluator}  ")
    lines.append(f"**评估日期**: {result.date}  ")
    lines.append("")

    # 总评分
    bar = _score_bar(result.total_score)
    lines.append(f"## 🏆 综合评分: {result.total_score:.2f} / {result.max_score:.2f} {bar}")
    lines.append("")
    lines.append(f"**评级**: {rating}")
    lines.append(f"**评语**: {rating_desc}")
    lines.append("")

    # 雷达图数据（文本）
    lines.append("## 📈 类别得分概览")
    lines.append("")
    lines.append("| 类别 | 得分 | 可视化 | 类别权重 | 加权贡献 |")
    lines.append("|------|-----:|:-------|---------:|---------:|")
    for cat in result.categories:
        bar = _score_bar(cat.average_score)
        color = _color_for_score(cat.average_score)
        lines.append(
            f"| {color} **{cat.category_name}** | "
            f"{cat.average_score:.2f} | {bar} | "
            f"{cat.weight * 100:.0f}% | {cat.weighted_score:.2f} |"
        )
    lines.append("")
    lines.append(f"**总分**: {result.total_score:.2f} / {result.max_score:.2f}")
    lines.append("")

    # 逐项详细评分
    lines.append("## 📋 详细评分明细")
    lines.append("")

    for cat in result.categories:
        color = _color_for_score(cat.average_score)
        lines.append(f"---")
        lines.append(f"### {color} [{cat.category_id}] {cat.category_name} ({cat.category_name_en})")
        lines.append(f"**类别得分**: {cat.average_score:.2f}/5.0 {_score_bar(cat.average_score)}")
        lines.append(f"**类别权重**: {cat.weight * 100:.0f}%")
        lines.append("")

        for item in cat.item_scores:
            color2 = _color_for_score(item.average_score)
            lines.append(f"#### {color2} {item.item_id} {item.item_name} ({item.item_name_en})")
            lines.append(f"**项目得分**: {item.average_score:.2f}/5.0 {_score_bar(item.average_score)}  ")
            lines.append(f"**项目权重**: {item.weight * 100:.0f}%")
            lines.append("")
            lines.append("| 子准则 | 评分 | 可视化 | 评分依据 |")
            lines.append("|--------|-----:|:-------|:---------|")
            for sub in item.sub_scores:
                color3 = _color_for_score(float(sub.score))
                bar = _score_bar(float(sub.score))
                lines.append(
                    f"| {color3} {sub.criterion_name} | "
                    f"**{sub.score}**/5 | {bar} | "
                    f"{sub.evidence} |"
                )
            lines.append("")

    # 总结和建议
    lines.append("## 💡 改进建议")
    lines.append("")

    # 找出评分最低的 3 个项目
    all_items = []
    for cat in result.categories:
        for item in cat.item_scores:
            all_items.append((item.average_score, cat.category_name, item.item_name))
    all_items.sort(key=lambda x: x[0])

    lines.append("### 优先改进项（得分最低）")
    lines.append("")
    for score, cat_name, item_name in all_items[:5]:
        color = _color_for_score(score)
        lines.append(f"- {color} **[{cat_name}] {item_name}**: {score:.2f}/5.0")
    lines.append("")

    lines.append("### 得分分布")
    lines.append("")
    total_subs = 0
    dist = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    for cat in result.categories:
        for item in cat.item_scores:
            for sub in item.sub_scores:
                total_subs += 1
                if sub.score in dist:
                    dist[sub.score] += 1
    for s in range(5, 0, -1):
        pct = dist[s] / total_subs * 100 if total_subs > 0 else 0
        bar_len = max(1, int(pct / 5))
        bar = "█" * bar_len
        label = {5: "卓越", 4: "较好", 3: "基本", 2: "不足", 1: "薄弱"}[s]
        lines.append(f"  {s}分 ({label}): {bar} {dist[s]}项 ({pct:.1f}%)")

    lines.append("")
    lines.append("---")
    lines.append(f"*报告由 Engineering Guideline Evaluation Framework 自动生成*")

    return "\n".join(lines)


def generate_json_report(result: EvaluationResult) -> str:
    """生成 JSON 格式的评估报告"""
    data = {
        "meta": {
            "project": result.project_name,
            "evaluator": result.evaluator,
            "date": result.date,
            "framework_version": "1.0",
        },
        "summary": {
            "total_score": result.total_score,
            "max_score": result.max_score,
            "rating": result.get_rating()[0],
            "rating_description": result.get_rating()[1],
        },
        "categories": [],
    }

    for cat in result.categories:
        cat_data = {
            "id": cat.category_id,
            "name": cat.category_name,
            "name_en": cat.category_name_en,
            "weight": cat.weight,
            "average_score": cat.average_score,
            "weighted_score": cat.weighted_score,
            "items": [],
        }
        for item in cat.item_scores:
            item_data = {
                "id": item.item_id,
                "name": item.item_name,
                "name_en": item.item_name_en,
                "weight": item.weight,
                "average_score": item.average_score,
                "sub_criteria": [],
            }
            for sub in item.sub_scores:
                item_data["sub_criteria"].append({
                    "id": sub.criterion_id,
                    "name": sub.criterion_name,
                    "score": sub.score,
                    "evidence": sub.evidence,
                    "weight": sub.weight,
                })
            cat_data["items"].append(item_data)
        data["categories"].append(cat_data)

    return json.dumps(data, ensure_ascii=False, indent=2)


def print_console_report(result: EvaluationResult) -> None:
    """在控制台打印格式化评估报告"""
    rating, rating_desc = result.get_rating()

    print("\n" + "=" * 72)
    print("  📊 工程准则评估报告")
    print("=" * 72)
    print(f"  项目       : {result.project_name}")
    print(f"  评估人     : {result.evaluator}")
    print(f"  评估日期   : {result.date}")
    print(f"  评级       : {rating}")
    print(f"  评语       : {rating_desc}")
    print()

    # 总分
    bar = _score_bar(result.total_score)
    print(f"  🏆 综合评分: {result.total_score:.2f} / {result.max_score:.2f} {bar}")
    print()

    # 类别概览
    print(f"  {'类别':<20} {'得分':<8} {'可视化':<24} {'权重':<8} {'加权':<8}")
    print(f"  {'─' * 20} {'─' * 8} {'─' * 24} {'─' * 8} {'─' * 8}")
    for cat in result.categories:
        color = _color_for_score(cat.average_score)
        bar = _score_bar(cat.average_score)
        print(f"  {color} {cat.category_name:<18} {cat.average_score:<8.2f} {bar:<24} "
              f"{cat.weight*100:<8.0f}% {cat.weighted_score:<8.2f}")
    print()

    # 详细评分
    print("  " + "─" * 72)
    print("  详细评分明细")
    print("  " + "─" * 72)
    print()

    for cat in result.categories:
        color = _color_for_score(cat.average_score)
        bar = _score_bar(cat.average_score)
        print(f"  {color} [{cat.category_id}] {cat.category_name}")
        print(f"     得分: {cat.average_score:.2f}/5.0 {bar} (权重: {cat.weight*100:.0f}%)")
        print()

        for item in cat.item_scores:
            color2 = _color_for_score(item.average_score)
            bar2 = _score_bar(item.average_score)
            print(f"    ● {color2} {item.item_id} {item.item_name}")
            print(f"      得分: {item.average_score:.2f}/5.0 {bar2}")
            print()

            for sub in item.sub_scores:
                color3 = _color_for_score(float(sub.score))
                bar3 = _score_bar(float(sub.score))
                evidence_display = sub.evidence if sub.evidence else "(无记录)"
                print(f"      {color3} [{sub.criterion_id}] {sub.criterion_name}")
                print(f"        评分: {sub.score}/5 {bar3}")
                print(f"        依据: {evidence_display}")
            print()

    # 改进建议
    print("  " + "─" * 72)
    print("  💡 改进建议")
    print("  " + "─" * 72)
    print()

    all_items = []
    for cat in result.categories:
        for item in cat.item_scores:
            all_items.append((item.average_score, cat.category_name, item.item_name))
    all_items.sort(key=lambda x: x[0])

    print("    优先改进项（得分最低）:")
    for score, cat_name, item_name in all_items[:5]:
        color = _color_for_score(score)
        print(f"      {color} [{cat_name}] {item_name}: {score:.2f}/5.0")

    print()
    print("    得分分布:")
    total_subs = 0
    dist = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    for cat in result.categories:
        for item in cat.item_scores:
            for sub in item.sub_scores:
                total_subs += 1
                if sub.score in dist:
                    dist[sub.score] += 1
    for s in range(5, 0, -1):
        pct = dist[s] / total_subs * 100 if total_subs > 0 else 0
        bar_len = max(1, int(pct / 5))
        bar = "█" * bar_len
        label = {5: "卓越", 4: "较好", 3: "基本", 2: "不足", 1: "薄弱"}[s]
        print(f"    {s}分 ({label}): {bar} {dist[s]}项 ({pct:.1f}%)")

    print()
    print("=" * 72)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  第四部分：自动化检测器（部分准则的代码分析）                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class AutoDetector:
    """自动化代码分析检测器集合"""

    @staticmethod
    def check_circular_imports(project_path: str) -> Tuple[int, str]:
        """检测循环导入（B02-01 无循环依赖）"""
        # 简单检测：扫描所有 Python 文件中的 import 并构建依赖图
        import ast
        import collections

        py_files = {}
        for root, dirs, files in os.walk(project_path):
            # 跳过常见的忽略目录
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.env', 'dist', 'build', '.mypy_cache', '.pytest_cache'
            )]
            for f in files:
                if f.endswith('.py'):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, project_path)
                    py_files[rel] = full

        # 构建模块依赖图
        dep_graph = collections.defaultdict(set)
        for rel_path, full_path in py_files.items():
            try:
                with open(full_path, 'r', encoding='utf-8') as fh:
                    tree = ast.parse(fh.read(), filename=full_path)
                # 只检查 from/import 语句
                module_name = rel_path.replace('\\', '/').replace('.py', '').replace('/', '.')
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            dep_graph[module_name].add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            dep_graph[module_name].add(node.module.split('.')[0])
            except Exception:
                pass

        # DFS 检测环
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {m: WHITE for m in dep_graph}
        cycles = []

        def dfs(node, path):
            color[node] = GRAY
            for neighbor in dep_graph.get(node, set()):
                if neighbor in dep_graph:
                    if color[neighbor] == GRAY:
                        # 发现环
                        cycle_path = path + [neighbor]
                        cycle_start = cycle_path.index(neighbor)
                        cycles.append(" → ".join(cycle_path[cycle_start:]))
                    elif color[neighbor] == WHITE:
                        dfs(neighbor, path + [neighbor])
            color[node] = BLACK

        for node in dep_graph:
            if color[node] == WHITE:
                dfs(node, [node])

        if cycles:
            evidence = f"发现 {len(cycles)} 个循环依赖: {'; '.join(cycles[:5])}"
            if len(cycles) > 5:
                evidence += f" ... (共 {len(cycles)} 个)"
            return max(1, 5 - len(cycles)), evidence
        else:
            return 5, "未检测到循环依赖，依赖图结构良好。"

    @staticmethod
    def check_module_size(project_path: str) -> Tuple[int, str]:
        """检测模块大小是否合理（A01-03 模块拆分合理性）"""
        large_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.gitignore'
            )]
            for f in files:
                if f.endswith('.py'):
                    full = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full)
                        with open(full, 'r', encoding='utf-8') as fh:
                            line_count = sum(1 for _ in fh)
                        rel = os.path.relpath(full, project_path)
                        if line_count > 500:
                            large_files.append((rel, line_count, size))
                    except Exception:
                        pass

        large_files.sort(key=lambda x: -x[1])

        if len(large_files) == 0:
            return 5, "所有 Python 文件均在合理大小范围内。"
        elif len(large_files) <= 2:
            details = "; ".join(f"{f[0]}({f[1]}行)" for f in large_files)
            return 4, f"有 {len(large_files)} 个文件偏大（>500行）: {details}"
        elif len(large_files) <= 5:
            details = "; ".join(f"{f[0]}({f[1]}行)" for f in large_files[:5])
            return 3, f"有 {len(large_files)} 个文件偏大: {details}"
        elif len(large_files) <= 10:
            return 2, f"有 {len(large_files)} 个大文件，建议重构拆分。"
        else:
            return 1, f"有 {len(large_files)} 个大文件，存在严重的模块拆分问题。"

    @staticmethod
    def check_print_statements(project_path: str) -> Tuple[int, str]:
        """检测 print 语句使用（E02-03 无 print 残留）"""
        print_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.mypy_cache', '.pytest_cache'
            )]
            for f in files:
                if f.endswith('.py'):
                    full = os.path.join(root, f)
                    try:
                        with open(full, 'r', encoding='utf-8') as fh:
                            for i, line in enumerate(fh, 1):
                                stripped = line.strip()
                                if stripped.startswith('print(') or stripped == 'print':
                                    rel = os.path.relpath(full, project_path)
                                    print_files.append(f"{rel}:{i}")
                                    break
                    except Exception:
                        pass

        if len(print_files) == 0:
            return 5, "未在 Python 文件中发现 print 语句残留。"
        elif len(print_files) <= 3:
            return 4, f"发现少量 print 语句: {', '.join(print_files)}"
        elif len(print_files) <= 10:
            return 2, f"发现 {len(print_files)} 处 print 语句，建议替换为 logging。"
        else:
            return 1, f"发现 {len(print_files)} 处 print 语句，存在系统性使用 print 替代 logging 的问题。"

    @staticmethod
    def check_test_existence(project_path: str) -> Tuple[int, str]:
        """检测测试文件存在性（D01 测试策略初步）"""
        test_count = 0
        test_method_count = 0
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.mypy_cache', '.pytest_cache'
            )]
            for f in files:
                if f.startswith('test_') and f.endswith('.py'):
                    test_count += 1
                    full = os.path.join(root, f)
                    try:
                        with open(full, 'r', encoding='utf-8') as fh:
                            for line in fh:
                                if line.strip().startswith('def test_'):
                                    test_method_count += 1
                    except Exception:
                        pass

        py_files_count = 0
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.mypy_cache', '.pytest_cache'
            )]
            for f in files:
                if f.endswith('.py') and not f.startswith('test_'):
                    py_files_count += 1

        ratio = test_method_count / max(py_files_count, 1)

        if ratio >= 3.0:
            return 5, f"测试充分: {test_method_count} 个测试方法分布在 {test_count} 个文件中。"
        elif ratio >= 1.5:
            return 4, f"测试较充分: {test_method_count} 个测试方法，建议继续补充。"
        elif ratio >= 0.5:
            return 3, f"测试中等: {test_method_count} 个测试方法，需加强覆盖。"
        elif ratio > 0:
            return 2, f"测试不足: 仅 {test_method_count} 个测试方法，需大幅补充。"
        else:
            return 1, "未发现测试文件，测试体系缺失。"

    @staticmethod
    def check_hardcoded_config(project_path: str) -> Tuple[int, str]:
        """检测硬编码配置（E01 配置管理）"""
        suspicious_patterns = [
            'sqlite3.connect', 'create_engine', 'conn_string',
            'password=', 'api_key', 'secret',
        ]
        hardcoded = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in (
                '__pycache__', '.git', 'node_modules', 'venv', '.venv',
                'env', '.mypy_cache', '.pytest_cache'
            )]
            for f in files:
                if f.endswith('.py'):
                    full = os.path.join(root, f)
                    try:
                        with open(full, 'r', encoding='utf-8') as fh:
                            for i, line in enumerate(fh, 1):
                                for pat in suspicious_patterns:
                                    if pat in line and 'config' not in line.lower() and 'env' not in line.lower():
                                        rel = os.path.relpath(full, project_path)
                                        hardcoded.append(f"{rel}:{i} ({pat})")
                                        break
                    except Exception:
                        pass

        if len(hardcoded) == 0:
            return 5, "未检测到明显的硬编码配置。"
        elif len(hardcoded) <= 3:
            return 4, f"发现少量可能的硬编码: {', '.join(hardcoded)}"
        elif len(hardcoded) <= 10:
            return 2, f"发现 {len(hardcoded)} 处可能的硬编码，建议配置化。"
        else:
            return 1, f"发现 {len(hardcoded)} 处硬编码，存在系统性问题。"


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  第五部分：主入口 & CLI                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def list_all_items(engine: EvaluationEngine) -> None:
    """列出所有评估项目"""
    print("\n" + "=" * 80)
    print("  📋 工程准则评估框架 — 评估项目清单")
    print("=" * 80)

    for cat in engine.categories:
        print(f"\n{'─' * 80}")
        print(f"  📁 [{cat.id}] {cat.name} ({cat.name_en})")
        print(f"  权重: {cat.weight * 100:.0f}% | {cat.description}")
        print(f"{'─' * 80}")

        for item in cat.items:
            print(f"\n  ◆ {item.id} {item.name} ({item.name_en})")
            print(f"    权重: {item.weight * 100:.0f}%")
            print(f"    核心问题: {item.key_question}")
            print(f"    描述: {item.description}")
            print(f"    子准则 ({len(item.sub_criteria)} 项):")
            for sub in item.sub_criteria:
                print(f"      ├─ [{sub.id}] {sub.name}")
                print(f"      │  {sub.description}")
            print()

    print(f"\n总计: {len(engine.categories)} 个类别, "
          f"{sum(len(c.items) for c in engine.categories)} 个评估项目, "
          f"{sum(len(c.items) for c in engine.categories for _ in c.items)} 个子准则")
    print()


def main():
    """主入口"""
    categories = _build_categories()
    engine = EvaluationEngine(categories)

    if len(sys.argv) < 2:
        # 交互模式
        result = engine.interactive_evaluate()
        print_console_report(result)

        # 保存报告
        save = input("\n保存 Markdown 报告? (y/n, 默认 y): ").strip().lower()
        if save != 'n':
            fname = f"evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            md_report = generate_markdown_report(result)
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(md_report)
            print(f"  报告已保存至: {fname}")

        save_json = input("保存 JSON 报告? (y/n, 默认 n): ").strip().lower()
        if save_json == 'y':
            fname = f"evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            json_report = generate_json_report(result)
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(json_report)
            print(f"  JSON 报告已保存至: {fname}")

    elif sys.argv[1] == '--list':
        list_all_items(engine)

    elif sys.argv[1] == '--auto' and len(sys.argv) >= 3:
        project_path = sys.argv[2]
        if not os.path.isdir(project_path):
            print(f"错误: 路径不存在或不是目录: {project_path}")
            sys.exit(1)

        # 加载自动检测器到对应的子准则
        detector = AutoDetector()
        for cat in categories:
            for item in cat.items:
                for sub in item.sub_criteria:
                    if sub.id == 'B02-01':
                        sub.auto_check = detector.check_circular_imports
                    elif sub.id == 'A01-03':
                        sub.auto_check = detector.check_module_size
                    elif sub.id == 'E02-03':
                        sub.auto_check = detector.check_print_statements
                    elif sub.id == 'D01-01':
                        sub.auto_check = detector.check_test_existence
                    elif sub.id == 'E01-01':
                        sub.auto_check = detector.check_hardcoded_config

        result = engine.auto_evaluate(project_path)
        print_console_report(result)

        # 自动保存报告
        fname = f"auto_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        md_report = generate_markdown_report(result)
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(md_report)
        print(f"  自动报告已保存至: {fname}")

    elif sys.argv[1] == '--report' and len(sys.argv) >= 3:
        # 从 JSON 文件生成报告
        json_path = sys.argv[2]
        if not os.path.isfile(json_path):
            print(f"错误: 文件不存在: {json_path}")
            sys.exit(1)
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 重建评分对象
        categories_scores = []
        for cat_data in data.get('categories', []):
            item_scores = []
            for item_data in cat_data.get('items', []):
                sub_scores = [
                    SubScore(
                        criterion_id=s['id'],
                        criterion_name=s['name'],
                        score=s['score'],
                        evidence=s.get('evidence', ''),
                        weight=s.get('weight', 1.0),
                    )
                    for s in item_data.get('sub_criteria', [])
                ]
                iscore = ItemScore(
                    item_id=item_data['id'],
                    item_name=item_data['name'],
                    item_name_en=item_data.get('name_en', ''),
                    weight=item_data.get('weight', 1.0),
                    sub_scores=sub_scores,
                )
                iscore.compute()
                item_scores.append(iscore)

            cscore = CategoryScore(
                category_id=cat_data['id'],
                category_name=cat_data['name'],
                category_name_en=cat_data.get('name_en', ''),
                weight=cat_data.get('weight', 0),
                item_scores=item_scores,
            )
            cscore.compute()
            categories_scores.append(cscore)

        meta = data.get('meta', {})
        result = EvaluationResult(
            project_name=meta.get('project', 'Unknown'),
            evaluator=meta.get('evaluator', 'Unknown'),
            date=meta.get('date', 'Unknown'),
            categories=categories_scores,
        )
        result.compute()

        print_console_report(result)

        md = generate_markdown_report(result)
        out_name = f"report_from_json_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(out_name, 'w', encoding='utf-8') as f:
            f.write(md)
        print(f"  Markdown 报告已保存至: {out_name}")

    else:
        print("用法:")
        print("  python engineering_evaluation.py              # 交互式评估")
        print("  python engineering_evaluation.py --auto <路径> # 自动化检测评估")
        print("  python engineering_evaluation.py --list       # 列出所有评估项目")
        print("  python engineering_evaluation.py --report <json> # 从 JSON 生成报告")


if __name__ == "__main__":
    main()
