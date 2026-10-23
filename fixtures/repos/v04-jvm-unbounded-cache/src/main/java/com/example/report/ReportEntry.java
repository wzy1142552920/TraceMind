package com.example.report;

public class ReportEntry {
    private final String reportId;
    private final String payload;

    public ReportEntry(String reportId, String payload) {
        this.reportId = reportId;
        this.payload = payload;
    }

    public String getReportId() {
        return reportId;
    }
}
