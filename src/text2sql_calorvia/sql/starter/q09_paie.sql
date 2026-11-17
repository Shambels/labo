-- Starter question 9. Work-accident absences (ACC) per person and site: first day, last day, working days.
-- One timesheet row per working day, so count(*) is the number of working days.
SELECT d.site_code, t.employee_id, MIN(t.work_date) AS du, MAX(t.work_date) AS au, COUNT(*) AS jours_ouvres
FROM timesheets t
JOIN contracts c ON c.employee_id = t.employee_id
                AND t.work_date BETWEEN c.start_date AND COALESCE(c.end_date, DATE '9999-12-31')
JOIN departments d USING (department_code)
WHERE t.absence_code = 'ACC'
  AND d.site_code = 'GENT'
  AND t.work_date >= DATE '2025-11-01' AND t.work_date < DATE '2025-12-01'
GROUP BY d.site_code, t.employee_id
