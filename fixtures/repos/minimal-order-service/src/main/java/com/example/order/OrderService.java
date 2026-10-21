package com.example.order;

import org.springframework.stereotype.Service;

@Service
public class OrderService {
    private final OrderMapper orderMapper;

    public OrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public void handlePaid(Long orderId) {
        this.updateStatus(orderId, "PAID");
    }

    public int updateStatus(Long orderId, String status) {
        if (orderId == null) {
            throw new IllegalArgumentException("orderId is null");
        }
        int rows = orderMapper.updateStatus(orderId, status);
        if (rows == 0) {
            // Failure path used by the synthetic incident log.
            throw new IllegalStateException("update failed for orderId=" + orderId);
        }
        return rows;
    }

    public int updateStatus(Long orderId) {
        return updateStatus(orderId, "PAID");
    }

    public static class Nested {
        public String ping() {
            return "pong";
        }
    }
}
