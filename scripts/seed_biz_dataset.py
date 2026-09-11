"""企业模拟业务数据集生成器（方案 P3 / C3）。

贯通「客户 → 销售订单 → 合同 → 库存/发货 → 收款 → 业绩」完整业务流程。
数据量：约 2000 客户 / 6000 订单 / 3000 合同 / 300 产品 / 4500 收款（可 --scale 缩放）。
幂等：重复执行先清空 biz_* 再重灌（仅对 tenant_id 目标租户）。

用法：
  python scripts/seed_biz_dataset.py --tenant 2 [--scale 0.2]
"""
import argparse
import random
import string
import sys
from datetime import datetime, timedelta

import pymysql

random.seed(42)

INDUSTRIES = ["制造业", "零售业", "信息技术", "建筑业", "批发业", "住宿餐饮", "交通运输", "金融业"]
REGIONS = ["华东", "华南", "华北", "西南", "华中", "东北", "西北"]
LEVELS = ["A", "B", "C", "D"]
CREDIT = ["NORMAL", "NORMAL", "NORMAL", "NORMAL", "RISK", "BLOCKED"]

PRODUCT_CATS = {
    "办公设备": ("打印机", "投影仪", "碎纸机", "扫描仪", "复印机"),
    "网络设备": ("路由器", "交换机", "防火墙", "AP", "网线"),
    "服务器": ("塔式服务器", "机架服务器", "存储阵列", "GPU服务器", "刀片服务器"),
    "软件服务": ("ERP授权", "CRM授权", "OA授权", "运维服务", "云主机"),
}

ORDER_STATUS = ["CREATED", "CONFIRMED", "SHIPPED", "DONE", "DONE", "DONE", "CANCELLED"]
CONTRACT_STATUS = ["DRAFT", "SIGNED", "EXECUTING", "EXECUTING", "CLOSED", "CLOSED", "TERMINATED"]
PAY_METHOD = ["TRANSFER", "TRANSFER", "BILL", "CASH"]
WAREHOUSES = ["中心仓", "华东仓", "华南仓", "华北仓"]


def rnd_company():
    prefix = random.choice(["华", "东", "恒", "远", "金", "中", "天", "嘉", "联", "晟"])
    mid = random.choice(["创", "信", "达", "通", "瑞", "泰", "博", "源", "海", "科"])
    suffix = random.choice(["科技", "贸易", "实业", "信息", "机电", "商贸", "集团", "制造"])
    return prefix + mid + suffix + random.choice(["", "有限公司", "股份有限公司", "有限责任公司"])


def seed(tenant, scale):
    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aioa", charset="utf8mb4")
    cur = conn.cursor()
    n_customer = int(2000 * scale)
    n_product = int(300 * scale)
    n_order = int(6000 * scale)
    n_contract = int(3000 * scale)
    n_payment = int(4500 * scale)

    for t in ["biz_customer", "biz_product", "biz_sales_order", "biz_contract",
              "biz_inventory", "biz_payment"]:
        cur.execute(f"DELETE FROM {t} WHERE tenant_id=%s", (tenant,))
    conn.commit()

    # 产品
    products = []
    for i in range(n_product):
        cat = random.choice(list(PRODUCT_CATS))
        name = random.choice(PRODUCT_CATS[cat])
        sku = f"{cat[:2]}-{random.randint(10000, 99999)}"
        price = round(random.uniform(200, 200000), 2)
        cost = round(price * random.uniform(0.5, 0.8), 2)
        cur.execute(
            "INSERT INTO biz_product (tenant_id,sku,name,category,unit_price,cost) VALUES (%s,%s,%s,%s,%s,%s)",
            (tenant, sku, f"{name}{i}", cat, price, cost))
        products.append((cur.lastrowid, name, cat, price))
    conn.commit()

    # 客户
    customers = []
    for i in range(n_customer):
        name = rnd_company()
        cur.execute(
            "INSERT INTO biz_customer (tenant_id,name,industry,region,level,credit_status) VALUES (%s,%s,%s,%s,%s,%s)",
            (tenant, name, random.choice(INDUSTRIES), random.choice(REGIONS),
             random.choice(LEVELS), random.choice(CREDIT)))
        customers.append(cur.lastrowid)
    conn.commit()

    # 订单 + 合同 + 收款（时间跨度近 12 个月，形成趋势）
    base = datetime.now() - timedelta(days=365)
    for i in range(n_order):
        cid = random.choice(customers)
        pid = random.choice(products)[0]
        qty = random.randint(1, 200)
        price = random.choice(products)[3]
        amount = round(qty * price, 2)
        ordered = base + timedelta(days=random.randint(0, 360),
                                   hours=random.randint(0, 23), minutes=random.randint(0, 59))
        status = random.choice(ORDER_STATUS)
        delivered = (ordered + timedelta(days=random.randint(1, 15))) if status in ("SHIPPED", "DONE") else None
        no = f"SO{tenant}{ordered:%Y%m%d}{i:05d}"
        cur.execute(
            "INSERT INTO biz_sales_order (tenant_id,order_no,customer_id,product_id,quantity,amount,status,ordered_at,delivered_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant, no, cid, pid, qty, amount, status, ordered, delivered))
        order_id = cur.lastrowid
        # 完成订单大概率有收款
        if status == "DONE" and random.random() < 0.7:
            paid = delivered + timedelta(days=random.randint(1, 20))
            cur.execute(
                "INSERT INTO biz_payment (tenant_id,payment_no,order_id,customer_id,amount,method,paid_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (tenant, f"PY{tenant}{paid:%Y%m%d}{i:05d}", order_id, cid, amount,
                 random.choice(PAY_METHOD), paid))
    conn.commit()

    for i in range(n_contract):
        cid = random.choice(customers)
        amount = round(random.uniform(10000, 5000000), 2)
        signed = base + timedelta(days=random.randint(0, 360))
        status = random.choice(CONTRACT_STATUS)
        expires = signed + timedelta(days=random.randint(180, 1095))
        cur.execute(
            "INSERT INTO biz_contract (tenant_id,contract_no,customer_id,amount,status,signed_at,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (tenant, f"CT{tenant}{signed:%Y%m%d}{i:05d}", cid, amount, status, signed, expires))
    conn.commit()

    # 库存
    for pid, name, cat, price in products:
        for wh in WAREHOUSES:
            cur.execute(
                "INSERT INTO biz_inventory (tenant_id,product_id,warehouse,quantity,safety_stock) "
                "VALUES (%s,%s,%s,%s,%s)",
                (tenant, pid, wh, random.randint(0, 5000), random.randint(50, 500)))
    conn.commit()

    # 收款兜底：DONE 未覆盖的再补一些
    cur.execute("SELECT COUNT(*) FROM biz_payment WHERE tenant_id=%s", (tenant,))
    have = cur.fetchone()[0]
    need = n_payment - have
    for i in range(max(0, need)):
        cid = random.choice(customers)
        paid = base + timedelta(days=random.randint(0, 360))
        cur.execute(
            "INSERT INTO biz_payment (tenant_id,payment_no,customer_id,amount,method,paid_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (tenant, f"PY{tenant}{paid:%Y%m%d}R{i:05d}", cid, round(random.uniform(1000, 500000), 2),
             random.choice(PAY_METHOD), paid))
    conn.commit()

    cur.close()
    conn.close()
    print(f"租户 {tenant} 数据集已生成：客户 {n_customer} / 产品 {n_product} / 订单 {n_order} / "
          f"合同 {n_contract} / 收款 {n_payment}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, default=2)
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()
    seed(args.tenant, args.scale)
