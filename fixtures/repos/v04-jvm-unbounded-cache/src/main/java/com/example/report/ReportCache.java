package com.example.report;

import java.util.concurrent.ConcurrentHashMap;

public final class ReportCache {
    private static final ConcurrentHashMap<String, ReportEntry> CACHE =
            new ConcurrentHashMap<>();

    private ReportCache() {
    }

    public static ReportEntry get(String reportId) {
        ReportEntry cached = CACHE.get(reportId);
        if (cached != null) {
            return cached;
        }
        ReportEntry loaded = ReportService.load(reportId);
        CACHE.put(reportId, loaded);
        return loaded;
    }
}
