import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Doctor Pharma Inventory App", layout="wide")

page = st.sidebar.selectbox(
    "Select Report", ["Mini Depo", "Commerce Depo", "Masina Depo", "Warehouse", "Combined Report", "Warehouse Current Stock"]
)

# Upload Excel Files
st.header("Upload Excel Files")
mini_file = st.file_uploader("Upload Mini Depo Excel", type=["xlsx", "xls"], key="mini")
commerce_file = st.file_uploader("Upload Commerce Depo Excel", type=["xlsx", "xls"], key="commerce")
masina_file = st.file_uploader("Upload Masina Depo Excel", type=["xlsx", "xls"], key="masina")
warehouse_file = st.file_uploader("Upload Warehouse Depo Excel (For Samples)", type=["xlsx", "xls"], key="warehouse")
warehouse_stock_file = st.file_uploader("Upload Warehouse Excel (Unfiltered – For Current Stock)", type=["xlsx", "xls"], key="warehouse_stock")

LEAD_TIME_MONTHS = 6


def extract_depot_data(uploaded_file):
    depot_data = {"sales": {}, "returns": {}, "inventory": {}, "invalid": []}
    if not uploaded_file:
        return depot_data

    try:
        xl = pd.ExcelFile(uploaded_file)
        df = pd.read_excel(xl, sheet_name="SNS", header=6)

        expected_cols = df.columns
        if len(expected_cols) < 14:
            st.error("File format issue: Not enough columns in SNS sheet.")
            return depot_data

        df = df[[expected_cols[1], expected_cols[4], expected_cols[11], expected_cols[12], expected_cols[13]]]
        df.columns = ["PName", "Month", "Sales", "Sales Return", "Grand Total"]
        df["Month"] = df["Month"].astype(str).str.strip()

        unique_months = df["Month"].dropna().unique().tolist()
        month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        sorted_months = sorted([m for m in unique_months if m in month_order], key=lambda x: month_order.index(x), reverse=True)
        EXPECTED_MONTHS = sorted_months[:5]

        df = df[df["Month"].isin(EXPECTED_MONTHS)]

        for drug, group in df.groupby("PName"):
            if len(group["Month"].unique()) < 2:
                depot_data["invalid"].append(drug)
                continue

            group["MonthOrder"] = group["Month"].map(lambda x: EXPECTED_MONTHS.index(x))
            group = group.sort_values("MonthOrder")

            sales = pd.to_numeric(group["Sales"], errors="coerce").fillna(0).abs().tolist()
            returns = pd.to_numeric(group["Sales Return"], errors="coerce").fillna(0).abs().tolist()
            grand_totals = pd.to_numeric(group["Grand Total"], errors="coerce").fillna(0).tolist()

            if len(sales) < 2 or len(returns) < 2:
                depot_data["invalid"].append(drug)
                continue

            depot_data["sales"][drug] = sales
            depot_data["returns"][drug] = returns
            depot_data["inventory"][drug] = sum(grand_totals)

    except Exception as e:
        st.error(f"Error processing file: {e}")

    return depot_data


def extract_warehouse_samples(warehouse_file):
    samples = {}
    try:
        df = pd.read_excel(warehouse_file, sheet_name="SNS", header=6)
        df.columns = df.columns.str.strip()
        df['PName'] = df['PName'].replace(r'^\s*$', np.nan, regex=True).fillna(method='ffill')
        df['Grand Total'] = pd.to_numeric(df['Grand Total'], errors='coerce')
        df_clean = df.dropna(subset=['PName', 'Grand Total'])
        grouped = df_clean.groupby('PName')['Grand Total'].sum()
        samples = grouped.to_dict()

        # Flip signs: samples are negative stock
        flipped_samples = {}
        for k, v in samples.items():
            if v < 0:
                flipped_samples[k] = abs(v)
            else:
                flipped_samples[k] = -v

        samples = flipped_samples

    except Exception as e:
        st.error(f"Error reading warehouse samples: {e}")

    return samples


def extract_warehouse_current_stock(file):
    current_stock = {}
    try:
        df = pd.read_excel(file, sheet_name="SNS", header=6)
        df.columns = df.columns.str.strip()
        df['PName'] = df['PName'].replace(r'^\s*$', np.nan, regex=True).fillna(method='ffill')
        df['Grand Total'] = pd.to_numeric(df['Grand Total'], errors='coerce')
        df_clean = df.dropna(subset=['PName', 'Grand Total'])
        grouped = df_clean.groupby('PName')['Grand Total'].sum()
        current_stock = grouped.to_dict()
    except Exception as e:
        st.error(f"Error reading warehouse stock file: {e}")
    return current_stock


def compute_combined_report(depots, sample_sales, warehouse_current_stock=None):
    combined_sales = {}

    all_drugs = set()
    for d in depots:
        all_drugs.update(d["sales"].keys())
    all_drugs.update(sample_sales.keys())

    if warehouse_current_stock:
        all_drugs.update(warehouse_current_stock.keys())

    for drug in all_drugs:
        sales_lists = [d["sales"].get(drug, []) for d in depots]
        return_lists = [d["returns"].get(drug, []) for d in depots]
        stock_list = [d["inventory"].get(drug, 0) for d in depots]

        sales_lists = [x + [0] * (5 - len(x)) if len(x) < 5 else x[:5] for x in sales_lists]
        return_lists = [x + [0] * (5 - len(x)) if len(x) < 5 else x[:5] for x in return_lists]

        total_sales = [sum(x) for x in zip(*sales_lists)] if sales_lists else [0] * 5
        total_returns = [sum(x) for x in zip(*return_lists)] if return_lists else [0] * 5

        sample_total = sample_sales.get(drug, 0)
        sample_monthly = sample_total / 5 if sample_total else 0
        total_sales = [s + sample_monthly for s in total_sales]

        total_sales_sum = sum(total_sales)
        total_returns_sum = sum(total_returns)
        total_net_sales = total_sales_sum - total_returns_sum

        if total_net_sales == 0:
            continue

        avg_demand = total_net_sales / 5
        demand = round(avg_demand, 2)

        # Include warehouse stock
        warehouse_stock = warehouse_current_stock.get(drug, 0) if warehouse_current_stock else 0
        stock = sum(stock_list) + warehouse_stock

        buffer = 0.1 * demand
        stock_to_hold = round((demand * LEAD_TIME_MONTHS) + buffer, 2)
        stock_diff = stock - stock_to_hold

        combined_sales[drug] = {
            "Net Monthly Demand": demand,
            "Combined Stock": stock,
            "Stock to Hold": stock_to_hold,
            "Excess": round(max(0, stock_diff), 2),
            "Shortfall": round(max(0, -stock_diff), 2),
            "Status": "Optimal" if abs(stock_diff) < 0.01 else ("Overstocked" if stock_diff > 0 else "Understocked"),
            "Includes Samples": "Yes" if sample_total != 0 else "No"
        }

    return combined_sales


def display_depot_report(depot_name, file):
    st.subheader(f"{depot_name} – Inventory Report")
    if not file:
        st.warning(f"Please upload a file for {depot_name}.")
        return

    data = extract_depot_data(file)
    if not data["sales"]:
        st.error(f"No valid drugs with 2+ months of data in {depot_name}.")
        return

    report = []
    for drug in data["sales"]:
        net = [(s - r) for s, r in zip(data["sales"][drug], data["returns"].get(drug, []))]
        avg = round(sum(net) / len(net), 2)
        buffer = avg * 0.1
        stock_to_hold = round((avg * LEAD_TIME_MONTHS) + buffer, 2)
        stock = data["inventory"].get(drug, 0)
        diff = stock - stock_to_hold

        report.append({
            "Drug": drug,
            "Net Monthly Demand": avg,
            "Current Stock": stock,
            "Stock to Hold": stock_to_hold,
            "Excess": round(max(0, diff), 2),
            "Shortfall": round(max(0, -diff), 2),
            "Status": "Optimal" if abs(diff) < 0.01 else ("Overstocked" if diff > 0 else "Understocked")
        })

    st.success(f"Showing inventory report for {depot_name}")
    df = pd.DataFrame(report).set_index("Drug")
    st.dataframe(df)

    if data["invalid"]:
        st.warning("The following drugs were skipped (less than 2 months of data):")
        st.write(", ".join(data["invalid"]))


# ROUTING
if page == "Mini Depo":
    display_depot_report("Mini Depo", mini_file)

elif page == "Commerce Depo":
    display_depot_report("Commerce Depo", commerce_file)

elif page == "Masina Depo":
    display_depot_report("Masina Depo", masina_file)

elif page == "Warehouse":
    st.title("Warehouse – Sample Sales Summary")
    if not warehouse_file:
        st.warning("Please upload the Warehouse Excel file.")
    else:
        samples = extract_warehouse_samples(warehouse_file)
        if not samples:
            st.error("No SAMPLE sales found in the Warehouse data.")
        else:
            df = pd.DataFrame.from_dict(samples, orient="index", columns=["Sample Sales"])
            st.success("Displaying Sample Sales from Warehouse")
            st.dataframe(df)

elif page == "Warehouse Current Stock":
    st.title("Warehouse – Current Stock Summary")
    if not warehouse_stock_file:
        st.warning("Please upload the Unfiltered Warehouse Excel file.")
    else:
        stock = extract_warehouse_current_stock(warehouse_stock_file)
        if not stock:
            st.error("No stock data found.")
        else:
            df = pd.DataFrame.from_dict(stock, orient="index", columns=["Current Stock"])
            st.success("Displaying Current Stock (All drugs)")
            st.dataframe(df)

elif page == "Combined Report":
    st.title("Combined Inventory Report – All Depots Including Samples")
    if not (mini_file and commerce_file and masina_file and warehouse_file):
        st.warning("Please upload all four files including warehouse.")
    else:
        mini = extract_depot_data(mini_file)
        commerce = extract_depot_data(commerce_file)
        masina = extract_depot_data(masina_file)
        samples = extract_warehouse_samples(warehouse_file)
        warehouse_current_stock = extract_warehouse_current_stock(warehouse_stock_file) if warehouse_stock_file else {}
        combined = compute_combined_report([mini, commerce, masina], samples, warehouse_current_stock)
        df = pd.DataFrame.from_dict(combined, orient="index")
        st.success("Displaying Combined Report Across Depots")
        st.dataframe(df)
