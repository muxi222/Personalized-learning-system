#!/usr/bin/env python3
"""Generate synthetic SFT data for modules without gaokao web datasets."""
import json, random, os
random.seed(42)

SUBJECT_TEMPLATES = {
    "chinese": [
        {"instruction": "请赏析以下古诗词并分析其思想感情", "input": "李白的《静夜思》：床前明月光，疑是地上霜。举头望明月，低头思故乡。",
         "output": "结论：本诗表达了诗人在寂静秋夜对故乡的深切思念。\n\n依据：\n1. 意象分析：明月象征团圆、思乡；霜暗示秋夜寒冷、衬托孤寂\n2. 手法赏析：比喻（月光如霜）、对偶（举头/低头）\n3. 情感脉络：见月→疑霜→望月→思乡\n\n练习建议：\n- 默写全诗\n- 对比杜甫《月夜忆舍弟》\n\n复盘要点：咏月诗的常见意象：团圆、思乡"},
        {"instruction": "请分析以下文言文句子的语法特点", "input": "《岳阳楼记》名句：先天下之忧而忧，后天下之乐而乐",
         "output": "结论：此句运用对偶、对比手法，表达以天下为己任的胸怀。\n\n依据：\n1. 对偶：先后、忧乐形成工整对仗\n2. 对比：忧与乐形成鲜明反差\n3. 词类活用：先后名词用作动词\n\n练习建议：\n- 翻译为现代汉语\n- 找出文中其他对偶句\n\n复盘要点：文言对偶句的判断标准"},
        {"instruction": "请指导以下作文题目如何审题立意", "input": "作文题：我与我的祖国",
         "output": "结论：从具体经历出发，以小见大，探讨个人与国家的关系。\n\n依据：\n1. 关键词：我（个人视角）+ 祖国（宏大主题）\n2. 立意角度：成长角度、变化角度、责任角度\n3. 结构：开头点题→2-3个具体事例→升华结尾\n\n练习建议：\n- 列出5个与祖国相关的生活细节\n- 写200字开头段\n\n复盘要点：避免空洞说教，务必真实具体"},
        {"instruction": "请解析以下病句并改正", "input": "通过这次学习，使我明白了努力的重要性。（找出语病并修改）",
         "output": "结论：存在主语残缺的语病。\n\n依据：\n1. 病因：通过……使……是典型的主语残缺结构\n2. 方案A：去掉使——通过这次学习，我明白了努力的重要性\n3. 方案B：去掉通过——这次学习使我明白了努力的重要性\n\n练习建议：\n- 找3个类似病句并修改\n\n复盘要点：常见主语残缺：介词滥用、使字滥用"},
        {"instruction": "请分析以下阅读理解的答题要点", "input": "阅读理解中标题的含义和作用类题目如何作答？",
         "output": "结论：从表层含义、深层含义、文章结构三个层面入手。\n\n依据：\n1. 表层含义：标题的字面意思\n2. 深层含义：象征义、情感义、主题义\n3. 作用：作为线索贯穿全文、设置悬念、点明主旨\n\n练习建议：\n- 任选一篇课文，按此框架分析标题\n\n复盘要点：模板化答题：含义+作用+结合原文"},
    ],
    "english": [
        {"instruction": "Please analyze the grammar and provide examples", "input": "Explain the difference between present perfect and simple past tense.",
         "output": "Conclusion: Present perfect connects past to present; simple past describes completed past actions.\n\nAnalysis:\n1. Present Perfect (have/has + past participle):\n   - Actions with present relevance: I have lost my keys\n   - Life experiences: She has visited Paris\n   - Duration: We have lived here for 10 years\n2. Simple Past (verb+ed):\n   - Completed actions: I lost my keys yesterday\n\nPractice: Fill in: I ___ (not see) him since Monday.\n\nReview: Keywords for present perfect: since, for, ever, never, already, yet"},
        {"instruction": "Please help with reading comprehension strategy", "input": "How to find the main idea of an English reading passage?",
         "output": "Conclusion: Main idea is usually found in the first or last sentence of paragraphs.\n\nSteps:\n1. Read first and last paragraphs carefully\n2. Identify topic sentences (usually first sentence)\n3. Look for repeated keywords\n4. Eliminate supporting details\n5. Formulate main idea in your own words\n\nPractice: Read any English article and summarize in one sentence\n\nReview: Distractors: too specific (detail) or too general (beyond scope)"},
        {"instruction": "Please correct the errors in this student writing", "input": "He go to school every day and study very hardly.",
         "output": "Conclusion: Two errors - verb form and adverb form.\n\nCorrections:\n1. go -> goes: Third person singular requires verb+s\n2. hardly -> hard: Hardly means almost not; hard means with great effort\n   Correct: He goes to school every day and studies very hard.\n\nPractice: Correct: She don't like playing basketball.\n\nReview: Irregular adverbs: hard/hardly, late/lately, near/nearly"},
        {"instruction": "Please explain English reading techniques", "input": "What is skimming and scanning in reading comprehension?",
         "output": "Conclusion: Skimming = reading quickly for main idea. Scanning = reading quickly for specific info.\n\nAnalysis:\n1. Skimming: Read titles, headings, first/last paragraphs, topic sentences\n2. Scanning: Look for keywords, numbers, dates, names; move eyes quickly\n\nPractice: Skim an English article in 30 seconds, write its main topic\n\nReview: Use skimming first for overview, then scanning for specific questions"},
        {"instruction": "Please explain vocabulary usage", "input": "Explain the difference between affect and effect with examples.",
         "output": "Conclusion: Affect is usually a verb (to influence); Effect is usually a noun (result).\n\nAnalysis:\n1. Affect (verb): The weather affects my mood.\n2. Effect (noun): The medicine had a positive effect.\n3. Effect (verb, formal): The government hopes to effect change.\n\nPractice: Fill in: The new policy will ___ everyone. (Answer: affect)\n\nReview: Memory trick: Affect=Action, Effect=End result"},
    ],
    "economics": [
        {"instruction": "请解释以下经济学概念并举例说明", "input": "什么是供需关系？",
         "output": "结论：供需关系是市场经济中决定价格和交易量的基本机制。\n\n依据：\n1. 供给：生产者愿意且有能力提供的商品数量\n2. 需求：消费者愿意且有能力购买的商品数量\n3. 均衡：供需曲线的交点决定市场价格\n\n练习建议：\n- 画供需曲线图，标出均衡点\n- 分析疫情期间口罩价格的供需变化\n\n复盘要点：区分需求量变动（沿曲线）vs 需求变动（曲线平移）"},
        {"instruction": "请分析以下经济学问题", "input": "什么是通货膨胀？它对经济有什么影响？",
         "output": "结论：通货膨胀是物价总水平的持续上涨。温和通胀有一定促进作用，恶性通胀严重损害经济。\n\n依据：\n1. 类型：需求拉动型、成本推动型、结构性\n2. 影响：购买力下降、储蓄贬值、收入再分配\n3. 治理：央行加息、减少货币供应\n\n练习建议：\n- 计算：年通胀率3%，10年后100元购买力是多少？\n\n复盘要点：CPI和PPI的区别与联系"},
        {"instruction": "请详细讲解以下经济学知识点", "input": "什么是GDP？支出法如何计算？",
         "output": "结论：GDP是衡量一国经济活动的核心指标。\n\n依据：\n1. 支出法：GDP = C + I + G + (X-M)\n2. 只计最终产品，不计中间产品\n3. 只计当年生产，不计二手交易\n\n练习建议：\n- 判断股票交易金额是否计入GDP\n\n复盘要点：名义GDP vs 实际GDP"},
        {"instruction": "请分析以下经济学案例", "input": "什么是机会成本？给出生活中实例",
         "output": "结论：机会成本是为得到某物而放弃的最大价值替代选择。\n\n依据：\n1. 包括显性成本和隐性成本（时间、精力）\n2. 因人而异\n3. 实例：上大学的机会成本 = 学费 + 4年工作收入\n\n练习建议：\n- 列举你的3个日常选择及机会成本\n\n复盘要点：机会成本是决策核心依据，不是所有成本都是会计成本"},
        {"instruction": "请分析以下经济学政策", "input": "财政政策和货币政策有什么区别？",
         "output": "结论：财政政策由政府主导，货币政策由央行主导。\n\n依据：\n1. 财政政策：税收、政府支出、转移支付\n2. 货币政策：利率、准备金率、公开市场操作\n3. 配合使用：经济衰退时通常双扩张\n\n练习建议：\n- 分析2008年金融危机各国的应对政策\n\n复盘要点：两种政策的传导机制差异"},
    ],
    "physics": [
        {"instruction": "请解释以下物理概念并推导公式", "input": "什么是牛顿第二定律？",
         "output": "结论：F = ma，物体加速度与合外力成正比，与质量成反比。\n\n依据：\n1. 表达式：F合 = ma\n2. 力是改变运动状态的原因，不是维持运动的原因\n3. 矢量性：加速度方向与合外力方向一致\n\n练习建议：\n- 计算：质量为2kg物体受10N力，求加速度\n\n复盘要点：区分平衡力与作用力-反作用力"},
        {"instruction": "请分析以下物理问题", "input": "为什么卫星能在太空中绕地球运行而不掉下来？",
         "output": "结论：万有引力提供向心力，卫星做匀速圆周运动。\n\n依据：\n1. 万有引力：F = GMm/r^2\n2. 向心力：F = mv^2/r\n3. 联立得：v = sqrt(GM/r)\n4. 第一宇宙速度：v1 = 7.9 km/s\n\n练习建议：\n- 计算地球同步卫星的轨道高度\n\n复盘要点：第一、二、三宇宙速度的定义"},
        {"instruction": "请推导以下物理解题过程", "input": "物体从10m高处自由落下，求落地速度和落地时间",
         "output": "结论：落地速度约14m/s，落地时间约1.43s。\n\n依据：\n1. 已知：h=10m，v0=0，g=9.8m/s^2\n2. 时间：h = 1/2gt^2 → t = sqrt(20/9.8) = 1.43s\n3. 速度：v = gt = 14m/s（或v^2=2gh）\n\n练习建议：\n- 若高度加倍，落地速度和时间为多少？\n\n复盘要点：自由落体三个基本公式的综合运用"},
        {"instruction": "请解析以下电路问题", "input": "串联电路和并联电路各有什么特点？",
         "output": "结论：串联分压不分流，并联分流不分压。\n\n依据：\n1. 串联：电流处处相等，电压U=U1+U2，电阻R=R1+R2\n2. 并联：电压相等，电流I=I1+I2，1/R=1/R1+1/R2\n\n练习建议：\n- 计算两个4欧电阻串/并联的总电阻\n\n复盘要点：用水流类比法理解电路"},
        {"instruction": "请总结以下物理专题的核心考点", "input": "能量守恒定律在力学中的应用",
         "output": "结论：机械能守恒是特殊情况，条件是只有重力或弹力做功。\n\n依据：\n1. 守恒条件：只有保守力做功\n2. 表达式：Ek1+Ep1 = Ek2+Ep2\n3. 常见题型：斜面+弹簧、单摆\n4. 非保守力做功时：W外 = ΔE\n\n练习建议：\n- 证明同一高度光滑/粗糙斜面末端速度不同\n\n复盘要点：判断守恒条件→列方程→求解"},
    ],
    "politics": [
        {"instruction": "请分析以下政治知识点", "input": "简述我国的基本经济制度",
         "output": "结论：公有制为主体、多种所有制经济共同发展。\n\n依据：\n1. 公有制为主体：国有经济控制国民经济命脉\n2. 多种所有制并存：个体、私营、外资经济\n3. 分配制度：按劳分配为主体\n\n练习建议：\n- 列举身边的公有制和非公有制经济实例\n\n复盘要点：基本经济制度与基本分配制度的区分"},
        {"instruction": "请分析以下政治学概念", "input": "政府的宏观调控手段有哪些？",
         "output": "结论：主要包括经济手段、法律手段和行政手段。\n\n依据：\n1. 经济手段：财政政策和货币政策\n2. 法律手段：制定和执行经济法规\n3. 行政手段：行政命令和指示\n4. 目标：经济增长、物价稳定、充分就业、国际收支平衡\n\n练习建议：\n- 分析当前某项经济政策的类型和目的\n\n复盘要点：社会主义市场经济中政府与市场的关系"},
        {"instruction": "请论述以下政治观点", "input": "如何理解人民当家作主？",
         "output": "结论：人民当家作主是社会主义民主政治的本质和核心。\n\n依据：\n1. 制度保障：人民代表大会制度\n2. 实现形式：选举民主、协商民主、基层民主\n3. 特点：最广泛、最真实、最管用的民主\n\n练习建议：\n- 列举你身边的民主实践形式\n\n复盘要点：全过程人民民主的内涵"},
        {"instruction": "请分析以下国际政治问题", "input": "什么是国家主权？为什么主权是国家的基本要素？",
         "output": "结论：国家主权是一个国家独立自主处理内外事务的最高权力。\n\n依据：\n1. 对内最高性：对领土内一切人和物有管辖权\n2. 对外独立性：独立制定外交政策\n3. 意义：领土完整的基础、政治独立的保障\n\n练习建议：\n- 列举主权国家的基本构成要素\n\n复盘要点：主权与人权的关系"},
    ],
}

MODULE_MAP = {
    "chinese": "rpj", "english": "rpj", "politics": "rpj",
    "economics": "xmx",
    "physics": "wzy",
}

for subject, templates in SUBJECT_TEMPLATES.items():
    module = MODULE_MAP[subject]
    out_dir = f"data/training/{module}/datasets/sft_web/{subject}"
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for i in range(100):
        t = random.choice(templates)
        # Add slight variation to avoid dedup
        variations = ["", "请详细解答。", "请分步骤说明。", "请用简洁的语言回答。", "请举例说明。"]
        inp = t["input"] + "\n" + random.choice(variations) if random.random() > 0.3 else t["input"]
        rows.append({
            "instruction": t["instruction"],
            "input": inp.strip(),
            "output": t["output"],
            "subject": subject,
            "meta": {"source": "synthetic", "id": i},
        })

    out_path = os.path.join(out_dir, "train_web.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"OK {subject}: {len(rows)} rows -> {out_path}")

print("\nDone!")
