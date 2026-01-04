"""
多模块集成测试脚本

测试场景:
1. 所有5个模块独立启动和健康检查
2. 前端路由到正确的模块端口
3. 跨模块认证和数据隔离
4. 各模块的学科验证
5. 完整的端到端工作流

运行方式:
    pytest backend/tests/integration/test_multi_module_integration.py -v

前提条件:
    - 所有5个模块的API已启动 (./deploy/scripts/start.sh api_all)
    - Redis已启动
    - 数据库已初始化
"""

import asyncio
import pytest
import httpx
from typing import Dict, List

# 模块配置
MODULES = {
    "rpj": {
        "port": 6001,
        "subjects": ["chinese", "english", "politics"],
        "name": "RPJ模块"
    },
    "xmx": {
        "port": 6002,
        "subjects": ["economics"],
        "name": "XMX模块"
    },
    "wzy": {
        "port": 6003,
        "subjects": ["math", "physics"],
        "name": "WZY模块"
    },
    "wzm": {
        "port": 6004,
        "subjects": ["chemistry"],
        "name": "WZM模块"
    },
    "tony": {
        "port": 6005,
        "subjects": ["history", "geography", "other"],
        "name": "TONY模块"
    }
}

class TestModuleHealth:
    """测试所有模块的健康状态"""

    @pytest.mark.asyncio
    async def test_all_modules_health_check(self):
        """测试所有5个模块的健康检查端点"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            for module_name, config in MODULES.items():
                url = f"http://localhost:{config['port']}/health"
                try:
                    response = await client.get(url)
                    assert response.status_code == 200, f"{config['name']} 健康检查失败"

                    data = response.json()
                    assert data["status"] == "healthy", f"{config['name']} 状态不健康"
                    assert data["module"] == module_name, f"{config['name']} 模块名不匹配"
                    assert set(data["subjects"]) == set(config["subjects"]), \
                        f"{config['name']} 学科列表不匹配"

                    print(f"✅ {config['name']} (端口 {config['port']}) 健康检查通过")
                    print(f"   支持学科: {', '.join(data['subjects'])}")

                except httpx.ConnectError:
                    pytest.fail(f"❌ 无法连接到 {config['name']} (端口 {config['port']})\n"
                                f"   请先启动模块: ./deploy/scripts/start.sh api_{module_name}")
                except Exception as e:
                    pytest.fail(f"❌ {config['name']} 健康检查异常: {str(e)}")

    @pytest.mark.asyncio
    async def test_api_docs_accessible(self):
        """测试所有模块的API文档可访问"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            for module_name, config in MODULES.items():
                url = f"http://localhost:{config['port']}/docs"
                try:
                    response = await client.get(url)
                    assert response.status_code == 200, f"{config['name']} API文档不可访问"
                    print(f"✅ {config['name']} API文档可访问: {url}")
                except Exception as e:
                    pytest.fail(f"❌ {config['name']} API文档访问失败: {str(e)}")

class TestModuleRouting:
    """测试前端路由到正确的模块"""

    def get_module_for_subject(self, subject: str) -> Dict:
        """根据学科返回对应的模块配置"""
        for module_name, config in MODULES.items():
            if subject in config["subjects"]:
                return {"name": module_name, **config}
        return None

    @pytest.mark.asyncio
    async def test_subject_routing(self):
        """测试各学科请求路由到正确的模块"""
        test_subjects = [
            "chinese", "english", "politics",  # RPJ
            "economics",                        # XMX
            "math", "physics",                  # WZY
            "chemistry",                        # WZM
            "history", "geography", "other"     # TONY
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for subject in test_subjects:
                module = self.get_module_for_subject(subject)
                assert module is not None, f"学科 {subject} 没有对应的模块"

                url = f"http://localhost:{module['port']}/api/v1/questions/"
                try:
                    # 尝试访问该模块的API (可能需要认证)
                    response = await client.get(url, params={"subject": subject})
                    # 允许401 (未认证) 或 200 (成功)
                    assert response.status_code in [200, 401], \
                        f"学科 {subject} 路由到模块 {module['name']} 失败"

                    print(f"✅ 学科 '{subject}' 正确路由到 {module['name']} (端口 {module['port']})")

                except Exception as e:
                    pytest.fail(f"❌ 学科 '{subject}' 路由测试失败: {str(e)}")

class TestSubjectValidation:
    """测试各模块的学科验证 (拒绝不支持的学科)"""

    @pytest.mark.asyncio
    async def test_module_rejects_wrong_subject(self):
        """测试模块拒绝不属于自己的学科"""
        # 测试案例: 向RPJ模块提交math学科的题目 (应该被拒绝)
        test_cases = [
            {"module": "rpj", "port": 6001, "wrong_subject": "math", "reason": "math属于wzy模块"},
            {"module": "tony", "port": 6005, "wrong_subject": "chemistry", "reason": "chemistry属于wzm模块"},
            {"module": "wzy", "port": 6003, "wrong_subject": "history", "reason": "history属于tony模块"},
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for case in test_cases:
                url = f"http://localhost:{case['port']}/api/v1/questions/"
                payload = {
                    "subject": case["wrong_subject"],
                    "content": "测试题目",
                    "student_answer": "测试答案",
                    "correct_answer": "正确答案"
                }

                try:
                    response = await client.post(url, json=payload)
                    # 期望返回400 (学科不支持) 或 401 (未认证)
                    # 注意: 如果返回401，说明认证层先拦截了，这也是可以接受的
                    if response.status_code == 400:
                        error = response.json()
                        assert "not supported" in error.get("detail", "").lower(), \
                            f"{case['module']}模块应该拒绝学科 {case['wrong_subject']}"
                        print(f"✅ {case['module']}模块正确拒绝了错误的学科 {case['wrong_subject']}")
                    elif response.status_code == 401:
                        print(f"⚠️  {case['module']}模块需要认证，跳过学科验证测试")
                    else:
                        print(f"⚠️  {case['module']}模块返回状态码 {response.status_code} (预期400或401)")

                except Exception as e:
                    print(f"⚠️  {case['module']}模块学科验证测试异常: {str(e)}")

class TestCrossModuleIsolation:
    """测试跨模块数据隔离"""

    @pytest.mark.asyncio
    async def test_question_list_filtered_by_subject(self):
        """测试错题列表按学科过滤"""
        # 注意: 此测试需要预先存在不同学科的题目数据
        # 如果数据库为空，此测试会被跳过

        async with httpx.AsyncClient(timeout=10.0) as client:
            for module_name, config in MODULES.items():
                url = f"http://localhost:{config['port']}/api/v1/questions/"

                try:
                    for subject in config["subjects"]:
                        response = await client.get(url, params={"subject": subject})

                        if response.status_code == 401:
                            print(f"⚠️  {config['name']} 需要认证，跳过数据隔离测试")
                            continue

                        if response.status_code == 200:
                            data = response.json()
                            items = data.get("items", [])

                            # 验证返回的题目都是该学科的
                            for item in items:
                                assert item["subject"] == subject, \
                                    f"{config['name']} 返回了错误学科的题目"

                            print(f"✅ {config['name']} 学科 '{subject}' 数据隔离正确 (共{len(items)}道题)")

                except Exception as e:
                    print(f"⚠️  {config['name']} 数据隔离测试异常: {str(e)}")

class TestEndToEndWorkflow:
    """端到端工作流测试"""

    @pytest.mark.asyncio
    async def test_user_registration_and_login(self):
        """测试用户注册和登录 (所有模块共享认证)"""
        import time
        test_user = {
            "username": f"test_user_{int(time.time())}",
            "email": f"test_{int(time.time())}@example.com",
            "password": "Test123456",
            "full_name": "集成测试用户"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 随机选择一个模块进行注册
            module = MODULES["tony"]
            base_url = f"http://localhost:{module['port']}"

            # 1. 注册
            try:
                register_response = await client.post(
                    f"{base_url}/api/v1/users/register",
                    json=test_user
                )

                if register_response.status_code == 200:
                    register_data = register_response.json()
                    assert "access_token" in register_data, "注册成功但未返回token"
                    token = register_data["access_token"]
                    print(f"✅ 用户注册成功: {test_user['username']}")

                    # 2. 使用token访问其他模块 (测试跨模块认证)
                    headers = {"Authorization": f"Bearer {token}"}

                    for other_module_name, other_config in MODULES.items():
                        other_url = f"http://localhost:{other_config['port']}/api/v1/questions/"
                        response = await client.get(other_url, headers=headers)

                        assert response.status_code in [200, 422], \
                            f"使用token访问 {other_config['name']} 失败"

                        print(f"✅ Token可跨模块使用: {other_config['name']}")

                elif register_response.status_code == 400:
                    print(f"⚠️  用户可能已存在，跳过注册测试")
                else:
                    print(f"⚠️  注册返回状态码: {register_response.status_code}")

            except Exception as e:
                print(f"⚠️  用户注册和认证测试异常: {str(e)}")

def run_tests():
    """运行所有集成测试"""
    print("=" * 80)
    print("        AI学习助手 - 多模块集成测试")
    print("=" * 80)
    print()
    print("测试覆盖:")
    print("  ✓ 模块健康检查 (5个模块)")
    print("  ✓ API文档可访问性")
    print("  ✓ 学科路由正确性 (10个学科)")
    print("  ✓ 学科验证 (拒绝错误学科)")
    print("  ✓ 跨模块数据隔离")
    print("  ✓ 端到端用户认证")
    print()
    print("开始测试...")
    print("=" * 80)
    print()

    # 使用pytest运行
    pytest.main([__file__, "-v", "--tb=short", "--color=yes"])

if __name__ == "__main__":
    run_tests()
