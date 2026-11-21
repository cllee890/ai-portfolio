# 竞品价格监控

## 目标
定时抓取竞品的价格与可售状态，与上次结果比较，只把有意义的变化告知运营，并对抓取失败做重试与隔离。

## 设计要点
- **变化判定**：价格变动幅度 ≥ 5% 才告警；可售状态变化（上架/下架）总是告警。
- **首次抓取只建立基线**，不告警。
- **失败处理**：瞬时错误（超时、限流）指数退避重试 3 次；仍失败记为"抓取失败"，不影响其他商品，也不更新旧基线。
- **告警去重**：状态文件只在抓取成功后更新，同一变化不会反复告警。
- **抓取器可替换**：`SnapshotFetcher` 读取本地快照以便离线复现；接入真实页面或 API 时实现 `fetch(sku)` 即可。

## 目录结构
```
price-monitor/
├── monitor.py            # 监控主程序（纯标准库）
├── test_monitor.py       # 16 个单元测试
├── data/
│   ├── watchlist.csv     # 监控清单
│   └── snapshots/        # 两天的模拟抓取结果（11-20 含一次超时，11-21 有价格与库存变化）
└── reports/
    ├── alerts-2026-11-20.md
    ├── alerts-2026-11-21.md
    └── state.json        # 最近一次成功抓取的基线
```

## 运行说明
```bash
cd workflows/price-monitor
rm -f reports/state.json                                  # 清空基线，从头开始
python monitor.py --snapshot data/snapshots/2026-11-20.json   # 第一次：建立基线
python monitor.py --snapshot data/snapshots/2026-11-21.json   # 第二次：产生告警
python -m unittest test_monitor -v
```
生产环境可用 cron 每天运行，并把 `alerts-*.md` 推送到飞书或邮件。

## 示例输入输出
**输入**：`watchlist.csv` 中 3 个竞品 SKU；快照 `2026-11-21.json` 中键盘降价、鼠标下架、充电器恢复抓取。

**输出**（`reports/alerts-2026-11-21.md`，实际运行结果）：
```markdown
# 竞品价格告警（2026-11-21）

- 告警数：2
- 抓取失败：0

| SKU | 竞品 | 商品 | 类型 | 变化 |
|---|---|---|---|---|
| CMP-001 | ShopA | 无线静音键盘 K2 | PRICE | 39.90 → 34.90（-12.5%） |
| CMP-002 | ShopB | 静音鼠标 M3 | AVAILABILITY | True → False |
```
CMP-003 在 11-20 超时，没有基线，所以 11-21 恢复抓取时只建立基线，不产生告警。

## 注意事项
- 抓取真实竞品页面前，请确认目标网站的服务条款与 robots 规则，控制抓取频率。
- 价格可能因地区、会员或优惠券而不同，监控时应固定同一口径（地区、是否含税）。
- 告警只说明价格变化，不建议自动跟价，定价决策应人工判断。
