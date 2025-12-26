#!/usr/bin/env python3
"""
批量创建模块脚本
基于TONY模块模板创建rpj, xmx, wzy, wzm模块
"""
import os
import shutil
import re

# 模块配置
MODULES = {
    "rpj": {
        "port": 6001,
        "subjects": ["chinese", "english", "politics"],
        "app_name": "AI Learning Assistant - RPJ Module",
        "description": "语文、英语、政治",
    },
    "xmx": {
        "port": 6002,
        "subjects": ["economics"],
        "app_name": "AI Learning Assistant - XMX Module",
        "description": "经济学(纯英语)",
    },
    "wzy": {
        "port": 6003,
        "subjects": ["math", "physics"],
        "app_name": "AI Learning Assistant - WZY Module",
        "description": "数学、物理",
    },
    "wzm": {
        "port": 6004,
        "subjects": ["chemistry"],
        "app_name": "AI Learning Assistant - WZM Module",
        "description": "化学",
    },
}

BASE_DIR = "/Users/antonio/academic_work/learning_assistant/backend/modules"
TEMPLATE_MODULE = "tony"


def replace_module_name(content: str, old_module: str, new_module: str) -> str:
    """替换模块名称"""
    # 替换所有出现的模块名（保持大小写）
    content = content.replace(f"backend.modules.{old_module}", f"backend.modules.{new_module}")
    content = content.replace(f"modules/{old_module}", f"modules/{new_module}")
    content = content.replace(f"modules.{old_module}", f"modules.{new_module}")
    content = content.replace(old_module.upper(), new_module.upper())
    content = content.replace(old_module.capitalize(), new_module.capitalize())
    return content


def update_config_file(file_path: str, module_name: str, config: dict):
    """更新配置文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换模块名
    content = content.replace('MODULE_NAME: str = "tony"', f'MODULE_NAME: str = "{module_name}"')
    content = content.replace('APP_NAME: str = "AI Learning Assistant - TONY Module"',
                            f'APP_NAME: str = "{config["app_name"]}"')
    content = content.replace('PORT: int = 6005', f'PORT: int = {config["port"]}')

    # 替换学科列表
    old_subjects = '["history", "geography", "other"]'
    new_subjects = str(config["subjects"]).replace("'", '"')
    content = content.replace(f'SUBJECTS: List[str] = {old_subjects}',
                            f'SUBJECTS: List[str] = {new_subjects}')

    # 替换日志文件路径
    content = content.replace('LOG_FILE: str = "./logs/tony.log"',
                            f'LOG_FILE: str = "./logs/{module_name}.log"')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def update_main_file(file_path: str, module_name: str, config: dict):
    """更新main.py文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换描述
    module_upper = module_name.upper()
    description_section = f"""    ## {module_upper}模块 - {config["description"]}

    智能错题分析与举一反三推荐系统

    ### 支持学科:"""

    # 构建学科列表（使用emoji）
    subject_emojis = {
        "chinese": "📖",
        "english": "🔤",
        "politics": "🏛️",
        "economics": "💹",
        "math": "📐",
        "physics": "⚡",
        "chemistry": "🧪",
    }

    subject_names_cn = {
        "chinese": "语文",
        "english": "英语",
        "politics": "政治",
        "economics": "经济学",
        "math": "数学",
        "physics": "物理",
        "chemistry": "化学",
    }

    subjects_list = "\n".join([
        f"    - {subject_emojis.get(s, '📚')} {subject_names_cn.get(s, s.capitalize())} ({s.capitalize()})"
        for s in config["subjects"]
    ])

    description_section += "\n" + subjects_list

    # 使用正则替换描述部分
    content = re.sub(
        r'## TONY模块.*?### 支持学科:.*?(?=### 主要功能:)',
        description_section + "\n\n    ",
        content,
        flags=re.DOTALL
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def create_module(module_name: str, config: dict):
    """创建单个模块"""
    print(f"\n{'='*60}")
    print(f"创建模块: {module_name} (端口: {config['port']})")
    print(f"学科: {', '.join(config['subjects'])}")
    print(f"{'='*60}")

    # 源目录和目标目录
    source_dir = os.path.join(BASE_DIR, TEMPLATE_MODULE)
    target_dir = os.path.join(BASE_DIR, module_name)

    # 如果目标目录已存在，先删除
    if os.path.exists(target_dir):
        print(f"⚠️  目标目录已存在，删除: {target_dir}")
        shutil.rmtree(target_dir)

    # 复制整个目录
    print(f"📁 复制目录: {source_dir} -> {target_dir}")
    shutil.copytree(source_dir, target_dir)

    # 遍历所有文件并替换模块名
    for root, dirs, files in os.walk(target_dir):
        # 跳过__pycache__和.py后的临时文件
        dirs[:] = [d for d in dirs if d != '__pycache__']

        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)

                # 读取文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 替换模块名
                new_content = replace_module_name(content, TEMPLATE_MODULE, module_name)

                # 写回文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                print(f"  ✅ 处理文件: {os.path.relpath(file_path, target_dir)}")

    # 更新配置文件
    config_file = os.path.join(target_dir, "config.py")
    print(f"  🔧 更新配置: config.py")
    update_config_file(config_file, module_name, config)

    # 更新main.py
    main_file = os.path.join(target_dir, "main.py")
    print(f"  🔧 更新主文件: main.py")
    update_main_file(main_file, module_name, config)

    print(f"✅ 模块 {module_name} 创建完成！")


def main():
    """主函数"""
    print("="*60)
    print("批量创建模块 - 基于TONY模板")
    print("="*60)

    # 检查模板目录是否存在
    template_dir = os.path.join(BASE_DIR, TEMPLATE_MODULE)
    if not os.path.exists(template_dir):
        print(f"❌ 错误: 模板目录不存在: {template_dir}")
        return

    # 创建所有模块
    for module_name, config in MODULES.items():
        try:
            create_module(module_name, config)
        except Exception as e:
            print(f"❌ 创建模块 {module_name} 失败: {e}")

    print("\n" + "="*60)
    print("🎉 所有模块创建完成！")
    print("="*60)
    print("\n模块列表:")
    for module_name, config in MODULES.items():
        print(f"  - {module_name}: http://localhost:{config['port']} ({config['description']})")


if __name__ == "__main__":
    main()
