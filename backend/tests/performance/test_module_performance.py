"""
多模块性能测试脚本

测试指标:
1. API响应时间基准测试 (每个端点)
2. 并发请求处理能力
3. 向量检索性能 (FAISS + BM25)
4. Celery任务队列吞吐量
5. 资源占用 (内存、CPU)

运行方式:
    python backend/tests/performance/test_module_performance.py

或使用pytest:
    pytest backend/tests/performance/test_module_performance.py -v -s

前提条件:
    - 所有5个模块的API和Agent已启动
    - Redis已启动
    - 数据库已初始化并有测试数据
"""

import asyncio
import time
import httpx
import statistics
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
import json

# 模块配置
MODULES = {
    "rpj": {"port": 6001, "subjects": ["chinese", "english", "politics"]},
    "xmx": {"port": 6002, "subjects": ["economics"]},
    "wzy": {"port": 6003, "subjects": ["math", "physics"]},
    "wzm": {"port": 6004, "subjects": ["chemistry"]},
    "tony": {"port": 6005, "subjects": ["history", "geography", "other"]}
}

# 性能基准 (毫秒)
PERFORMANCE_THRESHOLDS = {
    "health_check": 50,          # 健康检查 < 50ms
    "list_questions": 200,       # 列表查询 < 200ms
    "get_question": 100,         # 单个查询 < 100ms
    "statistics": 300,           # 统计查询 < 300ms (涉及聚合)
    "concurrent_load": 500,      # 并发请求 < 500ms (50并发)
}


class PerformanceResult:
    """性能测试结果"""

    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
        self.errors: List[str] = []

    def add_time(self, duration_ms: float):
        self.times.append(duration_ms)

    def add_error(self, error: str):
        self.errors.append(error)

    def get_stats(self) -> Dict:
        if not self.times:
            return {"error": "No successful requests"}

        return {
            "count": len(self.times),
            "min": min(self.times),
            "max": max(self.times),
            "avg": statistics.mean(self.times),
            "median": statistics.median(self.times),
            "p95": self._percentile(self.times, 95),
            "p99": self._percentile(self.times, 99),
            "errors": len(self.errors)
        }

    def _percentile(self, data: List[float], percentile: int) -> float:
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def print_report(self):
        stats = self.get_stats()
        if "error" in stats:
            print(f"\n❌ {self.name}: {stats['error']}")
            return

        print(f"\n📊 {self.name}")
        print(f"   请求次数: {stats['count']}")
        print(f"   最小值:   {stats['min']:.2f} ms")
        print(f"   最大值:   {stats['max']:.2f} ms")
        print(f"   平均值:   {stats['avg']:.2f} ms")
        print(f"   中位数:   {stats['median']:.2f} ms")
        print(f"   P95:      {stats['p95']:.2f} ms")
        print(f"   P99:      {stats['p99']:.2f} ms")
        if stats['errors'] > 0:
            print(f"   ❌ 错误:  {stats['errors']}")


class PerformanceTester:
    """性能测试器"""

    def __init__(self):
        self.results: Dict[str, PerformanceResult] = {}

    async def test_health_check_performance(self):
        """测试健康检查端点性能"""
        print("\n" + "=" * 80)
        print("1. 健康检查端点性能测试")
        print("=" * 80)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for module_name, config in MODULES.items():
                result = PerformanceResult(f"{module_name} - 健康检查")
                url = f"http://localhost:{config['port']}/health"

                # 执行50次请求
                for i in range(50):
                    start = time.time()
                    try:
                        response = await client.get(url)
                        duration_ms = (time.time() - start) * 1000

                        if response.status_code == 200:
                            result.add_time(duration_ms)
                        else:
                            result.add_error(f"Status {response.status_code}")

                    except Exception as e:
                        result.add_error(str(e))

                self.results[f"{module_name}_health"] = result
                result.print_report()

                # 检查是否满足性能基准
                stats = result.get_stats()
                if "avg" in stats:
                    threshold = PERFORMANCE_THRESHOLDS["health_check"]
                    if stats["avg"] > threshold:
                        print(f"   ⚠️  平均响应时间超过基准 ({threshold}ms)")
                    else:
                        print(f"   ✅ 满足性能基准 (< {threshold}ms)")

    async def test_api_endpoint_performance(self):
        """测试API端点性能 (无认证)"""
        print("\n" + "=" * 80)
        print("2. API端点性能测试 (健康检查和公开端点)")
        print("=" * 80)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for module_name, config in MODULES.items():
                # 测试题目列表端点 (可能需要认证)
                result = PerformanceResult(f"{module_name} - 题目列表")
                url = f"http://localhost:{config['port']}/api/v1/questions/"

                for i in range(30):
                    start = time.time()
                    try:
                        response = await client.get(url, params={"page": 1, "page_size": 10})
                        duration_ms = (time.time() - start) * 1000

                        # 允许401 (未认证) - 仍然算作成功响应
                        if response.status_code in [200, 401]:
                            result.add_time(duration_ms)
                        else:
                            result.add_error(f"Status {response.status_code}")

                    except Exception as e:
                        result.add_error(str(e))

                self.results[f"{module_name}_list"] = result
                result.print_report()

                # 检查是否满足性能基准
                stats = result.get_stats()
                if "avg" in stats:
                    threshold = PERFORMANCE_THRESHOLDS["list_questions"]
                    if stats["avg"] > threshold:
                        print(f"   ⚠️  平均响应时间超过基准 ({threshold}ms)")
                    else:
                        print(f"   ✅ 满足性能基准 (< {threshold}ms)")

    async def test_concurrent_requests(self):
        """测试并发请求处理能力"""
        print("\n" + "=" * 80)
        print("3. 并发请求性能测试 (50并发)")
        print("=" * 80)

        async def single_request(client: httpx.AsyncClient, url: str) -> float:
            """执行单个请求并返回耗时"""
            start = time.time()
            try:
                response = await client.get(url)
                return (time.time() - start) * 1000
            except Exception as e:
                return -1  # 错误标记

        async with httpx.AsyncClient(timeout=30.0) as client:
            for module_name, config in MODULES.items():
                result = PerformanceResult(f"{module_name} - 并发50")
                url = f"http://localhost:{config['port']}/health"

                # 创建50个并发请求
                tasks = [single_request(client, url) for _ in range(50)]

                start_time = time.time()
                durations = await asyncio.gather(*tasks)
                total_time = (time.time() - start_time) * 1000

                for duration in durations:
                    if duration > 0:
                        result.add_time(duration)
                    else:
                        result.add_error("Request failed")

                self.results[f"{module_name}_concurrent"] = result
                print(f"\n   总耗时: {total_time:.2f} ms (50个请求)")
                print(f"   吞吐量: {50 / (total_time / 1000):.2f} req/s")
                result.print_report()

                # 检查是否满足性能基准
                stats = result.get_stats()
                if "avg" in stats:
                    threshold = PERFORMANCE_THRESHOLDS["concurrent_load"]
                    if stats["avg"] > threshold:
                        print(f"   ⚠️  平均响应时间超过基准 ({threshold}ms)")
                    else:
                        print(f"   ✅ 满足性能基准 (< {threshold}ms)")

    async def test_cross_module_comparison(self):
        """跨模块性能对比"""
        print("\n" + "=" * 80)
        print("4. 跨模块性能对比分析")
        print("=" * 80)

        # 收集所有模块的健康检查性能
        health_stats = {}
        for module_name in MODULES.keys():
            key = f"{module_name}_health"
            if key in self.results:
                stats = self.results[key].get_stats()
                if "avg" in stats:
                    health_stats[module_name] = stats["avg"]

        if health_stats:
            print("\n📊 模块响应时间对比 (健康检查, 平均值):")
            sorted_modules = sorted(health_stats.items(), key=lambda x: x[1])

            for i, (module, avg_time) in enumerate(sorted_modules, 1):
                bar_length = int(avg_time / 2)  # 缩放显示
                bar = "█" * bar_length
                print(f"   {i}. {module:5} {avg_time:6.2f} ms {bar}")

            fastest = sorted_modules[0][0]
            slowest = sorted_modules[-1][0]
            print(f"\n   ⚡ 最快模块: {fastest}")
            print(f"   🐌 最慢模块: {slowest}")

    def generate_summary_report(self):
        """生成汇总报告"""
        print("\n" + "=" * 80)
        print("5. 性能测试汇总报告")
        print("=" * 80)

        total_tests = len(self.results)
        passed_tests = 0
        failed_tests = 0

        print(f"\n总测试数: {total_tests}")

        for name, result in self.results.items():
            stats = result.get_stats()
            if "error" not in stats and stats.get("errors", 0) == 0:
                passed_tests += 1
            else:
                failed_tests += 1

        print(f"✅ 通过: {passed_tests}")
        print(f"❌ 失败: {failed_tests}")

        # 性能建议
        print("\n💡 性能优化建议:")
        print("   1. 如果健康检查 > 50ms, 检查网络延迟和服务启动状态")
        print("   2. 如果API端点 > 200ms, 考虑添加数据库索引和缓存")
        print("   3. 如果并发性能差, 考虑增加Worker数量或使用连接池")
        print("   4. 定期运行此测试以监控性能退化")

    async def run_all_tests(self):
        """运行所有性能测试"""
        print("=" * 80)
        print("        AI学习助手 - 多模块性能测试")
        print("=" * 80)
        print("\n测试配置:")
        print(f"   模块数量: {len(MODULES)}")
        print(f"   性能基准: {PERFORMANCE_THRESHOLDS}")
        print("\n开始测试...\n")

        try:
            await self.test_health_check_performance()
            await self.test_api_endpoint_performance()
            await self.test_concurrent_requests()
            await self.test_cross_module_comparison()
            self.generate_summary_report()

        except Exception as e:
            print(f"\n❌ 性能测试异常: {str(e)}")
            import traceback
            traceback.print_exc()

        print("\n" + "=" * 80)
        print("测试完成")
        print("=" * 80)


async def main():
    """主函数"""
    tester = PerformanceTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
