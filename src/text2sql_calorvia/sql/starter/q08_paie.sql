-- Starter question 8. Headcount under contract on a date, per site.
-- A contract row is one period (contracts and amendments): count distinct people whose row covers the date.
-- The site comes from the contract's department.
SELECT w.name AS site, COUNT(DISTINCT c.employee_id) AS personnes
FROM contracts c
JOIN departments d USING (department_code)
JOIN work_sites w ON w.site_code = d.site_code
WHERE c.start_date <= DATE '2026-05-31'
  AND (c.end_date IS NULL OR c.end_date >= DATE '2026-05-31')
GROUP BY w.name
ORDER BY w.name
