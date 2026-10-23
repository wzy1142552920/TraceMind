package com.example.report;

import org.springframework.stereotype.Service;

@Service
public class ReportService {
    public ReportEntry getReport(String reportId) {
        return ReportCache.get(reportId);
    }

    static ReportEntry load(String reportId) {
        return new ReportEntry(reportId, "x".repeat(1024));
    }
}
