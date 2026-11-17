-- Starter question 10. Telework days per month: timesheet rows with work_location = 'TELE'.
SELECT to_char(work_date, 'YYYY-MM') AS mois, COUNT(*) AS jours_teletravail
FROM timesheets
WHERE work_location = 'TELE'
  AND work_date >= DATE '2026-04-01' AND work_date < DATE '2026-06-01'
GROUP BY 1
ORDER BY 1
