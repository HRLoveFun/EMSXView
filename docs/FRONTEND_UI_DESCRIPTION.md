# EMSX Trading Tool - Frontend UI Description

## Overall Purpose

The **EMSX Trading Tool** is a Bloomberg EMSX (Equity Management System) order and route management dashboard. It provides traders and portfolio managers with real-time visibility into their orders and execution routes, with capabilities to monitor flagged orders based on customizable conditions, perform batch modifications, and manage route-level actions (cancel, modify price/quantity, change order type, apply broker strategies).

The system integrates with the Bloomberg Terminal for authentication and connects to a backend API for order and route data.

---

## Layout Overview

The application uses a **single-page application (SPA)** layout with a persistent header, tabbed content area, and footer:

```
+------------------------------------------------------------------+
|  HEADER: Toolbar (App Title, Order Count, Connection Status,     |
|           Refresh, Strategy Data Manager, Logout)                 |
+------------------------------------------------------------------+
|  TAB BAR: [Monitor] [Execution] [Settings]                           |
+------------------------------------------------------------------+
|                                                                   |
|  MAIN CONTENT AREA (varies by tab):                              |
|  - Monitor Board (conditional alerts)                            |
|  - Execution Board                                              |
|   - Orders Table (filterable, groupable, selectable)             |
|   - Routes Table (filterable, groupable, with actions)            |
|                                                                   |
|  +------------------------------------------------------------+  |
|  |  (Optional) Batch Operation Panel (appears when orders    |  |
|  |  are selected in Orders tab)                               |  |
|  +------------------------------------------------------------+  |
|                                                                  |
|  - Settings Board (toggle item)                                              |
|     - Broker algorithm (structure: broker list, algo list, parameter list)
|     - Parameter update frequency (table: parameter, frequency)
|                                                                   |
+------------------------------------------------------------------+
|  FOOTER: Version, Connection Info                                |
+------------------------------------------------------------------+
```

### Key Layout Components

1. **Toolbar (Header)** - Persistent top bar with app branding, data status, and controls
2. **Tab Navigation** - Three main views: Monitor, Execution, Settings
3. **Main Content Area** - Dynamic content based on selected tab
4. **Toast Notifications** - Overlay messages for operation feedback
5. **Footer** - Version and connection information

---

## Functional Description per Section

### 1. Toolbar (Header)

**Location:** Fixed top bar across all views

**Information Displayed:**
- Application title: "EMSX Trading Tool"
- Order count (varies by tab - filtered count for Orders, total for Monitor)
- Last updated timestamp
- Connection status indicator (Connected/Disconnected/Connecting)

**User Actions:**
- **Refresh** button - Manually fetch latest data from backend
- **Refresh dropdown** - Options for "Refresh Data" or "Clear Cache"
- **Strategy Data Manager** - Opens a dialog to import/export strategy configurations
- **Logout** button - Clears session and disconnects [issue: inactivated]

**Special Behaviors:**
- Connection status auto-checks every 30 seconds
- Real-time polling for orders/routes every 2 seconds (increases to 4 seconds when tab is hidden)
- Trader info refreshes every 30 seconds (cached)
- Loading spinner displayed during data fetches

---

### 2. Monitor Board (Default Tab)

**Purpose:** Display orders that match user-configurable alert conditions - helps traders identify orders requiring attention.

**Information Displayed:**
- Alert count badge showing total matching orders
- **Condition Panel** with configurable alert rules:
  - `$Value <` - Dollar value below threshold (default: $10,000)
  - `$Value >` - Dollar value above threshold (default: $49,000,000)
  - `%Chg >` - Buy orders with percentage change above threshold (default: 4.5%)
  - `%Chg < -` - Sell orders with percentage change below negative threshold (default: -4.5%)
  - `Qty/ADV >` - Order quantity as percentage of 5-day average daily volume (default: 5%)
  - **Odd Lot** - odd lot orders (quantity not multiple of round lot size). When the round lot size is unavailable from Bloomberg, the order is excluded from odd lot evaluation (shown as unknown) rather than defaulting to a lot size of 100
- **Subgroup by** dropdown to organize results by: Exchange, Ticker, Side, Status, Portfolio, Trader, Currency, or none

**Order Table Columns:**
- Order ID, Ticker, Side, Status, Type, Qty, %Filled, Limit Px, Avg Px, Arr Px, Last Px, Ivl VWAP, $Value, %Change, ADV 5D, Portfolio, Trader, Exchange, Currency, FX Rate, PM Note, Created, Flags

**User Actions:**
- **Enable/disable** individual conditions via checkboxes
- **Adjust thresholds** via numeric input fields (commits on blur or Enter)
- **Toggle boolean conditions** (Odd Lot)
- **Reset** all conditions to defaults
- **Sort** any column by clicking headers
- **Expand/collapse** condition groups and subgroups
- **View flags** - Each order row shows colored badges indicating which conditions it triggered

**Special Behaviors:**
- Conditions persist to localStorage (survives page refresh)
- Color-coded condition groups (amber for low value, red for high value, rose for % change, violet for Qty/ADV ratio, blue for odd lots)
- Conditional text highlighting (e.g., dollar values outside thresholds highlighted in red)
- Tooltips on hover show detailed breakdown (total/filled/remaining quantities)

---

### 3. Execution Board (Tab)


### 3.1 Order Panel
**Purpose:** Full order management view with filtering, grouping, selection, batch operations, and individual order modification.

**Information Displayed:**
- Groupable/filterable table of all orders
- Column headers with sort indicators and filter icons
- Group header bar showing current grouping option and count
- Footer showing "Showing X of Y orders" with group count and selection count

**Order Table Columns (24 columns):**
- Checkbox (selection), Order ID, Ticker, Side, Status, Type, Qty, %Filled, Limit Px, Avg Px, Arr Px, Last Px, Ivl VWAP, $Value, %Change, ADV 5D, Portfolio, Trader, Exchange, Currency, FX Rate, PM Note, Created, Actions

**User Actions:**
- **Group by** dropdown - Organize orders by: Exchange, Ticker, Side, Status, Portfolio, Trader, Currency, or disable grouping
- **Filter** - Each column header has a filter icon that opens a popover:
  - **Text filters** for: Ticker, Portfolio, Exchange, Currency (type to filter)
  - **Multi-select filters** for: Side (Buy/Sell), Status (11 options: NEW, WORKING, PARTIAL, FILLED, CANCELLED, COMPLETED, QUEUED, SUSPENDED, ASSIGN, PENDING_CANCEL, REJECTED), Order Type (4 options), Trader
  - **Clear filters** button appears when filters are active
- **Sort** - Click any column header to sort ascending/descending
- **Select orders** - Checkbox in first column; header checkbox selects all visible
- **Batch modify** - When orders are selected, a Batch Operation Panel appears
- **Modify Order** - Individual order modification via Actions column (edit icon) for eligible orders
- **Route Order** - Create child routes via Actions column (branch icon) for eligible orders

**Order Modification:**
Eligible orders (status: NEW, ASSIGN, WORKING with remaining quantity) display an edit icon in the Actions column. Clicking opens a modification dialog allowing changes to:
- **Order Type** - Limit, Market, Stop, Stop Limit
- **Limit Price** - Required for Limit and Stop Limit orders
- **Stop Price** - Required for Stop and Stop Limit orders
- **Quantity** - Must be greater than or equal to filled quantity
- **Time in Force** - Day, GTC, IOC, FOK

Changes are submitted to the backend via the EMSX API `ModifyOrderEx` request. Success/failure notifications are displayed via toast messages, and the order list refreshes automatically after successful modification.

**Special Behaviors:**
- Client-side filtering (instant, no network calls)
- Selected orders persist within session but clear on refresh
- Row highlighting for selected orders
- Collapsible groups (click group header to expand/collapse)
- Tooltips show quantity breakdown on hover
- Modify action only appears for eligible orders (NEW, ASSIGN, WORKING status with remaining quantity)

|**Order Routing:**
Eligible orders (status: NEW, ASSIGN, WORKING, PARTIAL with remaining quantity > 0) display a route icon (branch symbol) in the Actions column. The current trader must match the order's assigned trader to route it. Clicking opens the Route Order dialog allowing users to create a child route for execution:

**Route Order Dialog Fields:**
- **Broker** - Required. Select from available brokers loaded from broker algorithm configuration
- **Route Quantity** - Required. Amount to route (cannot exceed order's remaining quantity)
- **Order Type** - Required. Limit, Market, Stop, Stop Limit
- **Limit Price** - Required for Limit and Stop Limit orders
- **Stop Price** - Required for Stop and Stop Limit orders
- **Time in Force** - Required. Day, GTC, IOC, FOK
- **Exchange Destination** - Optional. Target exchange for execution (e.g., NYSE, NASDAQ)
- **Route Notes** - Optional. Notes for this specific route

**Eligibility Criteria:**
- Order status must be NEW, ASSIGN, WORKING, or PARTIAL
- Current terminal trader must match the order's assigned trader
- Order must have remaining quantity > 0
- Route quantity cannot exceed remaining quantity

The route is submitted to the backend via the EMSX API `RouteEx` request. Success creates a child route associated with the parent order. Success/failure notifications are displayed via toast messages, and both order and route lists refresh automatically after successful routing.

### 3.2 Route Panel

**Purpose:** View execution route details and perform route-level modifications.

**Information Displayed:**
- Two-level groupable table of all routes
- Route status badges with icons (color-coded by state)
- Action menu per row

**Route Table Columns (21 columns):**
- Order#, Route#, Ticker, Exchange, Side, Status, Type, Qty, %Filled, Filled, Working, Avg Px, Limit Px, Last Px, Last Shr, Broker, Trader, Strategy, Notes, Reason, Actions

**User Actions:**
- **Two-level grouping** - Primary and secondary group selectors (e.g., group by Exchange, then by Ticker)
- **Filter** options:
  - **Ticker** text filter
  - **Status** multi-select with Include/Exclude toggle
  - **Broker** multi-select with Include/Exclude toggle
  - **Trader** multi-select with Include/Exclude toggle
- **Sort** - Click column headers
- **Route Actions** (dropdown menu per row):
  - Cancel
  - Modify 

**Route Modification Dialogs:**
1. **Cancel** - Confirmation dialog
2. **Modify** - Modify Panel
  a. **Order Type** - Select type (Limit/Market/Stop/Stop Limit), prices, TIF
  b. **Limit Price** - Input new limit price
  c. **Amount** - Input new quantity
  d. **Broker** - Select broker
  e. **Strategy** - Select strategy, and strategy-specific fields
  Modify Panel Layout:
  row: Order Type， Limit Price, Amount
  row: cell with dropdown list, cell with positive value entry, soft alert, price >1.05 or < 0.95 last price, hard forbidden， price >1.1 or < 0.9 last price; cell with positive value entry, hard forbidden, larger than remaining quantity

**Special Behaviors:**
- Route status badges color-coded: Working (blue), Partial Fill (amber), Filled (green), Cancel (red), Queued (purple), etc.
- Collapsible primary and secondary group headers
- Filter indicator in footer with active filter summary


---

### 4. Batch Operation Panel

**Purpose:** Modify multiple selected orders at once.

**Appears When:** One or more orders are selected in the Orders tab

**Information Displayed:**
- Count of selected orders
- Ready badge indicating batch mode

**User Actions:**
- **Clear** - Deselect all orders
- **Batch Modify** button - Opens modal dialog

**Batch Modify Modal:**
- **Field to Modify** dropdown with options:
  - Limit Price
  - Order Quantity
  - Time in Force (Day, GTC, IOC, FOK)
  - Order Status (Cancel)
- **New Value** input (varies by field type)
- **Apply Changes** button (requires confirmation for cancellations)
- Error validation for invalid values
- Confirmation step for cancellations (destructive action warning)

**Special Behaviors:**
- Numeric fields validated for positive numbers
- Cancellation requires explicit confirmation
- Toast notifications show success/failure after operation

---

### 5. Settings Board

**Purpose:** Configure broker algorithms, parameter update frequencies, and global monitoring preferences. Broker algorithm data is automatically fetched from the EMSX API and persisted on the backend with daily freshness checks.

**Information Displayed:**
- Toggle switches for global settings
- Hierarchical broker algorithm tree view with freshness status
- Parameter configuration table
- Update frequency management table
- Last updated timestamp and refresh status

**User Actions:**

#### 5.1 Global Settings
- **Enable Monitor Alerts** - Toggle to activate/deactivate all alert conditions globally
- **Enable Desktop Notifications** - Toggle to enable/disable real-time desktop alert notifications

#### 5.2 Broker Algorithm Configuration

**Overview:**
The Broker Algorithm Configuration system provides a complete view of available brokers, their strategies, and strategy parameters. Data is fetched from the EMSX API using three endpoints:
- `GetBrokersWithAssetClass` - retrieves all enabled brokers
- `GetBrokerStrategiesWithAssetClass` - retrieves strategies for each broker
- `GetBrokerStrategyInfoWithAssetClass` - retrieves parameter details for each strategy

**Data Management:**
- **Initial Load:** On first application start, the frontend loads broker algorithm data in a 3-tier sequence: (1) localStorage cache for instant display, (2) backend stored data via a single `GET /api/broker-algorithms` request, (3) full Bloomberg API refresh via `POST /api/broker-algorithms/refresh` if backend data is stale or missing
- **Daily Refresh:** Each subsequent day when the frontend is opened, the system automatically checks data freshness and refreshes if needed
- **Manual Refresh:** Users can manually trigger a refresh using the "Refresh Now" button
- **Persistence:** Data is stored in `data/broker_algorithms.json` on the backend with timestamp tracking. The frontend also caches data in localStorage for instant startup

**Status Bar:**
- **Last Updated** - Shows when data was last fetched from Bloomberg
- **Refresh Status** - Indicates if data is up-to-date or needs refresh
- **Refresh Button** - Allows manual refresh of broker algorithm data

**Tree View Structure (3 levels):**
- Level 1: Ticker Composite Exchange 
- Level 2: Broker 
- Level 3: Algorithm 

**Parameter Table (for selected algorithm):**
- Columns: Name, Data Type, Value, Description
- Shows all configuration parameters for the selected algorithm
- Data types are inferred from field names and values (string/number/boolean)
- Value fields are editable inline (if not disabled)

**User Actions:**
- **Expand/collapse** tree nodes to navigate broker/algorithm hierarchy
- **Select algorithm** to view and edit parameters
- **Edit parameters** - Click to modify Value (respects Data Type and Disable flag)
- **Add Algorithm** - Opens dialog to create new algorithm with parameter template
- **Delete Algorithm** - Removes selected algorithm after confirmation
- **Save Changes** - Persists parameter modifications to backend
- **Refresh Now** - Manually trigger refresh from Bloomberg API

**API Endpoints:**
- `GET /api/broker-algorithms` - Retrieve stored broker algorithm configuration
- `POST /api/broker-algorithms/refresh` - Force refresh from Bloomberg API
- `GET /api/broker-algorithms/status` - Check data freshness status

**Special Behaviors:**
- Loading indicators shown while fetching data
- Empty state displayed if no data exists (prompts to refresh)
- Automatic daily refresh check on application startup
- Data version tracking for future migrations
- Strategy Data Manager provides import/export functionality

#### 5.3 Parameter Update Frequency

**Information Displayed:**
- Table of all algorithm parameters and system-level metrics
- Columns: Parameter Name | Current Frequency | Unit (seconds/minutes) | Last Updated

**User Actions:**
- **Modify Frequency** - Click dropdown on any row to select update interval:
  - Real-time
  - 5 seconds
  - 30 seconds
  - 1 minute
  - Custom
- **Save Changes** - Button to apply all frequency modifications
- View **Last Updated** timestamp for each parameter

**Special Behaviors:**
- Frequency changes apply after explicit save (not instant)
- Toast notification confirms successful frequency update
- Changes persist across sessions
- Real-time parameters refresh immediately; others follow configured schedule

---

### 6. Toast Notifications

**Purpose:** Provide feedback for user operations.

**Types:**
- **Success** (green) - Operation completed successfully
- **Error** (red) - Operation failed
- **Info** (blue) - Informational messages (e.g., cache cleared)

**Behavior:**
- Auto-dismiss after few seconds
- Manual dismiss via X button
- Stacked in bottom-right corner

---

### 7. Strategy Data Manager （Modify and Move to 5. Settings）

**Purpose:** Import/export strategy parameter configurations.

**Actions:**
- Import strategy data from JSON file
- Export current strategy data to JSON file

---

## User-Facing Details

### Configurable Options

1. **Monitor Conditions:**
   - Enable/disable each condition individually
   - Adjust numeric thresholds
   - Settings persist in localStorage

2. **Table Grouping:**
   - Orders: 8 grouping options + none
   - Routes: 8 primary grouping + 8 secondary grouping options

3. **Filters:**
   - Text-based for symbol/portfolio/exchange/currency/ticker
   - Multi-select for status/order type/trader
   - Include/Exclude mode for route filters

### Visual Indicators

- **Connection Status:** Green (connected), Red (disconnected), Pulsing (connecting)
- **Order Status Badges:** Color-coded by state (NEW, WORKING, PARTIAL, FILLED, CANCELLED, ASSIGN (cyan), PENDING_CANCEL (red), REJECTED (destructive), etc.)
- **Route Status Badges:** Icon + text with status-specific colors
- **Side Coloring:** Buy = green text, Sell = red text
- **Conditional Flags:** Color-coded badges on matching orders in Monitor view

### Toggles & Settings

- Monitor conditions stored in localStorage
- Filter state maintained per session (cleared on refresh)
- Selection state maintained per session (cleared on refresh)

---

## Assumptions & Missing Information

### Assumptions

1. **Authentication:** The system assumes Bloomberg Terminal handles authentication; no login screen is shown.
2. **Backend Availability:** Frontend polls backend every 2 seconds; assumes API endpoints exist at `/api/orders`, `/api/routes`, `/api/trader-info`, etc.
3. **Data Structure:** Order and Route types match Bloomberg EMSX API response format.
4. **Currency Support:** System appears to support multiple currencies with FX rate tracking.
5. **Odd Lot Feature:** Applies to markets configured in `ODD_LOT_MARKETS` setting. When Bloomberg does not return the round lot size for a security, the order is excluded from odd lot detection (displayed as unknown) rather than incorrectly flagging it based on a default value.

### Missing Information / Suggested Clarifications

1. **User Roles:** No visible indication of different user permission levels (e.g., trader vs. manager).
2. **Order Creation:** No ability to create new orders from the UI - only viewing and modification.
3. **Order Details Modal:** No drill-down to view complete order details.
4. **Route-Level Filtering:** Could benefit from additional filters like date range or order type.
5. **Export Functionality:** Monitor board could benefit from export to CSV/Excel.
6. **Keyboard Shortcuts:** No keyboard navigation or shortcuts documented.
7. **Accessibility:** No ARIA labels or screen reader support mentioned in code.
8. **Mobile Responsiveness:** Code includes `useMobile` hook but UI appears desktop-focused.
9. **Audit Trail:** No visible logging of user actions or modifications.
10. **Broker Strategy Fields:** Strategy parameters appear dynamic based on broker; may need documentation.

---

## Technical Stack (for reference)

- **Framework:** React 18 + TypeScript + Vite
- **UI Library:** Shadcn UI (customized components)
- **Styling:** Tailwind CSS
- **Icons:** Lucide React
- **State Management:** React hooks (useState, useMemo, useCallback)
- **Data Fetching:** Custom API service with polling
- **Caching:** In-memory cache with localStorage persistence

---

## Summary

The EMSX Trading Tool is a professional-grade trading dashboard focused on **order monitoring**, **order management**, and **route execution oversight**. Its three-tab architecture provides:
- **Monitor** - Alert-driven view for attention-worthy orders
- **Orders** - Full order list with powerful filtering, grouping, and batch operations
- **Routes** - Execution-level detail with modification capabilities

The UI emphasizes real-time data, customizable alerting, and efficient batch operations - suitable for active traders managing multiple orders across exchanges and portfolios.
