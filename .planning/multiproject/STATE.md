# AICTO 多项目军团管理状态

## 当前状态
- 已新增 `portfolio_manager.py`：构建 PM 项目 × Legion 军团组合态。
- 已新增 `legion_portfolio_status` 工具：只读输出项目健康、军团归属、积压与建议动作。
- 已修改 `dispatch_to_legion_balanced`：默认按项目归属过滤 commander。
- 已保留显式跨项目借兵开关：`allow_cross_project_borrow=true`。

## 验证结果
- ✅ Python 编译：`/Users/feijun/.hermes/hermes-agent/venv/bin/python -m py_compile hermes-plugin/*.py`
- ✅ 新增测试：`python -m unittest test_portfolio_manager -v`，5/5 PASS。
- ✅ 全量插件测试：`python -m unittest discover -p 'test_*.py' -v`，111/111 PASS。
- ✅ 插件注册 smoke：17 个工具，包含 `legion_portfolio_status`。
- ✅ 真实组合态 smoke：`legion_portfolio_status` 返回 success，识别 6 个 PM 项目、9 个 active commander、3 个 online commander。
