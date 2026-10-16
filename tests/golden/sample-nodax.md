# tmdl-lens-test-report

**Contents**

- [Overview](#overview)
- [1. Data Sources](#data-sources)
- [2. Table Details](#table-details)
- [3. Measures](#measures)
- [4. Functions](#functions)
- [5. Relationships](#relationships)
- [6. Security Roles](#security-roles)
- [7. M Parameters](#m-parameters)
- [⚠ Unresolved Sources](#unresolved)
- [8. Model Statistics](#statistics)

---

<a id="overview"></a>
## Overview

| Property | Value |
|---|---|
| **Culture** | en-US |
| **Compatibility Level** | 1605 |
| **Data Source Version** | powerBI_V3 |

---

<a id="data-sources"></a>
## 1. Data Sources

This model contains 3 loaded tables, 1 calculated table, 1 field parameter, 1 measures-only table, 1 calculation group, 1 not loaded, 7 measures, 3 relationships.

| Table | Source Type | Source |
|---|---|---|
| `dim-product` | Power Platform Dataflow | source-dataflow-platform -> Power Platform Dataflow -> product_dim |
| `fact-sales` | Power BI Dataflow | source-dataflow-standard -> Power BI Dataflow -> sales_fact |
| `helper-order-lookup` (hidden) | SQL | source-sql-staging -> source-sql-direct -> SQL -> fake-server.database.windows.net -> SalesDB -> dbo.orders |

### Support Tables

| Table | Type |
|---|---|
| `_measures` | Measures |
| `cg-time-intelligence` | Calculation Group |
| `dim-date` | Calculated (DAX) |
| `param-metric-selector` | Field Parameter |

### Not Loaded

> These tables have `enableLoad = false` and are not visible in the report.
> They are typically used as intermediate query steps.

| Table | Source Type | Source |
|---|---|---|
| `source-sql-staging` | SQL | source-sql-direct -> SQL -> fake-server.database.windows.net -> SalesDB -> dbo.orders |


**Not Loaded Table Format Strings Used (3 total, 2 unique)**

| Format String | Count | Columns |
|---|---|---|
| (none) | 2 | `status` (source-sql-staging), `internal_notes` (source-sql-staging) |
| `0` | 1 | `order_id` (source-sql-staging) |

---

<a id="table-details"></a>
## 2. Table Details

### `dim-product`

**Source:** Power Platform Dataflow  
**Entity:** `product_dim`  
**Chain:** `source-dataflow-platform -> Power Platform Dataflow -> product_dim`  

**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `product_id` | Text | - | none | `product_id` | - | Unique identifier for the product, sourced from the product dimension feed |  |
| `product_name` | Text | - | none | `product_name` | - | - |  |
| `category` | Text | - | none | `category` | - | Product category grouping used for merchandising reports |  |
| `unit_price` | Decimal | - | sum | `unit_price` | - | - |  |
| `product_url` | Text | - | none | `product_url` | - | - |  |

**Data Categories:** `product_url` = WebURL  

---

### `fact-sales`

**Source:** Power BI Dataflow  
**Entity:** `sales_fact`  
**Chain:** `source-dataflow-standard -> Power BI Dataflow -> sales_fact`  

**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `order_id` | Integer | `0` | none | `order_id` | - | - |  |
| `customer_id` | Text | - | none | `customer_id` | - | - |  |
| `order_date` | Date/Time | `Long Date` | none | `order_date` | - | - |  |
| `ship_date` | Date/Time | `Long Date` | none | `ship_date` | - | - |  |
| `amount` | Decimal | - | sum | `amount` | - | - |  |

**Measures**

| Measure | Format | Description | Hidden |
|---|---|---|---|
| `_Row Count Helper` | `#,##0` | - | Hidden |
| `Order Fulfillment Summary` | `0` | - |  |
---

### `helper-order-lookup`

**Source:** SQL  
**Table:** `dbo.orders`  
**Physical table:** `dbo.orders`  
**Server:** `fake-server.database.windows.net`  
**Database:** `SalesDB`  
**Chain:** `source-sql-staging -> source-sql-direct -> SQL -> fake-server.database.windows.net -> SalesDB -> dbo.orders`  
**Hidden:** Yes  

**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `order_id` | Integer | `0` | none | `order_id` | - | - |  |
| `status_code` | Text | - | none | `status` | - | - |  |

**Measures**

| Measure | Format | Description | Hidden |
|---|---|---|---|
| `Open Order Count` | `0` | - |  |
---

### `cg-time-intelligence`


**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `Name` | Text | - | - | `Name` | `Ordinal` | - |  |
| `Ordinal` | Integer | - | - | `Ordinal` | - | - |  |

**Calculation Items**

| Item | Ordinal | Format String |
|---|---|---|
| `YTD` | 0 | `SELECTEDMEASUREFORMATSTRING()` |
| `MTD` | 1 | `SELECTEDMEASUREFORMATSTRING()` |
| `Rolling 12M` | 2 | `SELECTEDMEASUREFORMATSTRING()` |
| `Prior Year` | 3 | `SELECTEDMEASUREFORMATSTRING()` |
| `YoY %` | 4 | `0.00%` |

> Calculation items can be applied to any measure at report-build time (via `SELECTEDMEASURE()`). TMDL has no static record of which measures a given item is actually used with.

---

### `dim-date`

**Source:** Calculated (DAX)  

**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `Date` | Date/Time | `Long Date` | none | `Date` | - | - |  |
| `Year` | Integer | `0` | none | `Year` | - | - |  |
| `MonthName` | Text | - | none | `MonthName` | `MonthNumber` | - |  |
| `MonthNumber` | Integer | `0` | none | `MonthNumber` | - | - |  |

**Key Column:** `Date`  

**Calculated Columns**

- `IsWeekend`
- `PriorYearFlag`

---

### `param-metric-selector`

**Source:** Field Parameter  

**Columns**

| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |
|---|---|---|---|---|---|---|---|
| `param-metric-selector` | - | - | none | `[Value1]` | `param-metric-selector Order` | - |  |
| `param-metric-selector Fields` | - | - | none | `[Value2]` | - | - | Hidden |
| `param-metric-selector Order` | - | `0` | sum | `[Value3]` | - | - | Hidden |

---


**Format Strings Used (23 total, 3 unique)**

| Format String | Count | Columns |
|---|---|---|
| (none) | 15 | `product_id` (dim-product), `product_name` (dim-product), `category` (dim-product), `unit_price` (dim-product), `product_url` (dim-product), `customer_id` (fact-sales), `amount` (fact-sales), `status_code` (helper-order-lookup), `Name` (cg-time-intelligence), `Ordinal` (cg-time-intelligence), `MonthName` (dim-date), `IsWeekend` (dim-date), `PriorYearFlag` (dim-date), `param-metric-selector` (param-metric-selector), `param-metric-selector Fields` (param-metric-selector) |
| `0` | 5 | `order_id` (fact-sales), `order_id` (helper-order-lookup), `Year` (dim-date), `MonthNumber` (dim-date), `param-metric-selector Order` (param-metric-selector) |
| `Long Date` | 3 | `order_date` (fact-sales), `ship_date` (fact-sales), `Date` (dim-date) |

<a id="measures"></a>
## 3. Measures

### General

| Measure | Table | Format | Description |
|---|---|---|---|
| `Total Sales Amount` | `_measures` | `#,##0.00` | - |
| `Order Count` | `_measures` | `#,##0` | - |
| `Avg Order Value` | `_measures` | `#,##0.00` | - |
| `Sales YTD` | `_measures` | `#,##0.00` | - |
| `_Row Count Helper` | `fact-sales` | `#,##0` | - |
| `Order Fulfillment Summary` | `fact-sales` | `0` | - |
| `Open Order Count` | `helper-order-lookup` | `0` | - |


**Format Strings Used (7 total, 3 unique)**

| Format String | Count | Measures |
|---|---|---|
| `#,##0.00` | 3 | `Total Sales Amount` (_measures), `Avg Order Value` (_measures), `Sales YTD` (_measures) |
| `#,##0` | 2 | `Order Count` (_measures), `_Row Count Helper` (fact-sales) |
| `0` | 2 | `Order Fulfillment Summary` (fact-sales), `Open Order Count` (helper-order-lookup) |

---

<a id="functions"></a>
## 4. Functions

| Function | Used By | Description |
|---|---|---|
| `AddTax` | - | Adds sales tax to a net amount using the given rate. |
| `SafeStockThreshold` | - | Returns the reorder threshold for a product category. |

---

<a id="relationships"></a>
## 5. Relationships

| From Table | From Column | To Table | To Column | Cardinality | Cross Filter | Security Filter |
|---|---|---|---|---|---|---|
| `fact-sales` | `order_date` | `dim-date` | `Date` | Many-to-One | bothDirections | oneDirection |
| `fact-sales` | `customer_id` | `dim-product` | `product_id` | Many-to-One | oneDirection | oneDirection |

**Inactive Relationships**

| From Table | From Column | To Table | To Column | Cross Filter | Security Filter |
|---|---|---|---|---|---|
| `fact-sales` | `ship_date` | `dim-date` | `Date` | oneDirection | bothDirections |

---

<a id="security-roles"></a>
## 6. Security Roles

| Role | Table | Filter | Dynamic |
|---|---|---|---|
| `Administrators` | - | - | No |
| `Area Supervisors` | `fact-sales` | `[region] = "South"` | No |
|  | `dim-product` | `[category] = "Hardware"` |  |
| `Employees` | `dim-product` | `USERPRINCIPALNAME() = [email]` | Yes (USERPRINCIPALNAME) |
| `Legacy Users` | `dim-product` | `USERNAME() = [username]` | Yes (USERNAME) |
| `Regional Managers` | `fact-sales` | `[region] = "North"` | No |

---

<a id="m-parameters"></a>
## 7. M Parameters

| Parameter | Type | Value | Used By |
|---|---|---|---|
| `ServerName` | Text | `fake-server.database.windows.net` | `source-from-parameter` |
| `DatabaseName` | Text | `SalesDB` | `source-from-parameter` |

> *Only direct parameter references in connector calls are shown.
> Parameters used in conditional logic or computed expressions may not appear here.*

---

<a id="unresolved"></a>
## ⚠ Unresolved Sources

The following sources could not be resolved statically.

| Expression | Reason |
|---|---|
| `source-via-custom-function` | no connector, combine or query reference found |

---

<a id="statistics"></a>
## 8. Model Statistics

| Category | Count | Items |
|---|---|---|
| Loaded Tables | 3 | `dim-product`, `fact-sales`, `helper-order-lookup` |
| Hidden Tables | 1 | `helper-order-lookup` |
| Calculated Tables | 1 | `dim-date` |
| Field Parameters | 1 | `param-metric-selector` |
| Measures-Only Tables | 1 | `_measures` |
| Calculation Groups | 1 | `cg-time-intelligence` |
| Not Loaded | 1 | `source-sql-staging` |
| Relationships | 3 | - |
| Measures | 7 | - |
| Calculated Columns | 2 | - |
| Columns | 12 | - |

---

*Generated by tmdl-lens*
