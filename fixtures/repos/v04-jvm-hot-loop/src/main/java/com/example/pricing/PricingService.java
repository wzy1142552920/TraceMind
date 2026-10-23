package com.example.pricing;

import org.springframework.stereotype.Service;

@Service
public class PricingService {
    private static final int ITERATIONS = 50_000;

    public long recalculate(long orderId) {
        long total = 0L;
        for (int i = 0; i < ITERATIONS; i++) {
            total += (orderId * 31L + i) % 9973;
        }
        return total;
    }
}
