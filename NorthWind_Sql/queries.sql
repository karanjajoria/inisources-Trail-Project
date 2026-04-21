-- =============================================================================
--  NORTHWIND DATABASE - SQL QUERY COLLECTION
--  Dialect  : MS SQL Server (T-SQL)
--  Database : Northwind (pre-restored)
--  Notes    : Where syntax differs across engines, inline comments mark the
--             PostgreSQL / SQLite alternative.
-- =============================================================================


-- =============================================================================
-- QUERY 1 : Total Revenue by Product Category
-- Revenue  = UnitPrice × Quantity × (1 - Discount)
-- Tables   : [Order Details], Products, Categories
-- Output   : CategoryName | TotalRevenue  (sorted highest → lowest)
-- =============================================================================

SELECT
    c.CategoryName,

    -- Sum the discounted line-item revenue across every order in that category.
    -- ROUND to 2 decimal places for clean currency output.
    ROUND(
        SUM(od.UnitPrice * od.Quantity * (1.0 - od.Discount)),
        2
    ) AS TotalRevenue

FROM [Order Details]  od                          -- line items

-- Each line item belongs to one product
INNER JOIN Products   p  ON p.ProductID   = od.ProductID

-- Each product belongs to one category
INNER JOIN Categories c  ON c.CategoryID  = p.CategoryID

GROUP BY
    c.CategoryID,       -- include the PK so the GROUP BY is unambiguous
    c.CategoryName

ORDER BY
    TotalRevenue DESC;  -- highest-revenue category first


-- =============================================================================
-- QUERY 2 : Top 10 Customers by Lifetime Order Value
-- Tables   : Customers, Orders, [Order Details]
-- Output   : CustomerID | CompanyName | TotalOrderValue | MostRecentOrderDate
-- =============================================================================

-- Use TOP 10 for SQL Server.
-- PostgreSQL / SQLite equivalent: remove TOP 10 and append  LIMIT 10  at the end.
SELECT TOP 10
    c.CustomerID,
    c.CompanyName,

    -- Lifetime revenue: sum all discounted line items across all orders
    ROUND(
        SUM(od.UnitPrice * od.Quantity * (1.0 - od.Discount)),
        2
    ) AS TotalOrderValue,

    -- Most recent order placed by this customer
    MAX(o.OrderDate) AS MostRecentOrderDate

FROM Customers      c

-- A customer may have many orders
INNER JOIN Orders         o  ON o.CustomerID = c.CustomerID

-- Each order may have many line items
INNER JOIN [Order Details] od ON od.OrderID   = o.OrderID

GROUP BY
    c.CustomerID,
    c.CompanyName

ORDER BY
    TotalOrderValue DESC;   -- highest spenders at the top


-- =============================================================================
-- QUERY 3 : All Delayed Orders
-- Condition: ShippedDate is more than 7 days after OrderDate
-- Tables   : Orders
-- Output   : OrderID | CustomerID | OrderDate | ShippedDate | DelayDays | Status
-- =============================================================================

SELECT
    o.OrderID,
    o.CustomerID,
    o.OrderDate,
    o.ShippedDate,

    -- Calculate the number of days between order placement and actual shipment.
    -- SQL Server  : DATEDIFF(day, OrderDate, ShippedDate)
    -- PostgreSQL  : (ShippedDate::date - OrderDate::date)
    -- SQLite      : JULIANDAY(ShippedDate) - JULIANDAY(OrderDate)
    DATEDIFF(day, o.OrderDate, o.ShippedDate) AS DelayDays,

    -- Literal label required by the spec
    'Delayed' AS Status

FROM Orders o

WHERE
    -- Only include rows where the order was actually shipped (exclude NULLs)
    o.ShippedDate IS NOT NULL

    -- Core delay condition: shipped more than 7 days after the order was placed
    AND DATEDIFF(day, o.OrderDate, o.ShippedDate) > 7

ORDER BY
    DelayDays DESC;   -- worst delays first for easy triage


-- =============================================================================
-- QUERY 4 : Stored Procedure — GetDelayedOrders
-- Encapsulates the same delayed-order logic from Query 3.
-- Accepts an optional @MinDelayDays parameter (default = 7) so callers can
-- adjust the threshold without editing the procedure body.
--
-- Usage examples:
--   EXEC GetDelayedOrders;           -- uses default 7-day threshold
--   EXEC GetDelayedOrders @MinDelayDays = 14;  -- 14-day threshold
-- =============================================================================

-- Drop the procedure first if it already exists so the script is re-runnable.
-- SQL Server 2016+ alternative: CREATE OR ALTER PROCEDURE …
IF OBJECT_ID('dbo.GetDelayedOrders', 'P') IS NOT NULL
    DROP PROCEDURE dbo.GetDelayedOrders;
GO

CREATE PROCEDURE dbo.GetDelayedOrders
    -- Caller can override the threshold; defaults to 7 days
    @MinDelayDays INT = 7
AS
BEGIN
    -- Prevent row-count messages from polluting result sets
    SET NOCOUNT ON;

    SELECT
        o.OrderID,
        o.CustomerID,
        o.OrderDate,
        o.ShippedDate,

        -- Days between order placement and shipment
        -- PostgreSQL equivalent : (ShippedDate::date - OrderDate::date)
        DATEDIFF(day, o.OrderDate, o.ShippedDate) AS DelayDays,

        -- Static status label
        'Delayed' AS Status

    FROM Orders o

    WHERE
        -- Exclude unshipped / in-transit orders (NULL ShippedDate)
        o.ShippedDate IS NOT NULL

        -- Apply the configurable delay threshold passed in by the caller
        AND DATEDIFF(day, o.OrderDate, o.ShippedDate) > @MinDelayDays

    ORDER BY
        DelayDays DESC;  -- worst delays first

END;
GO

-- =============================================================================
-- END OF FILE
-- =============================================================================