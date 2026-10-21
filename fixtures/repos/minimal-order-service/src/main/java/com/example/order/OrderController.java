package com.example.order;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping("/orders/paid")
    public String paid(Long orderId) {
        orderService.handlePaid(orderId);
        return "ok";
    }

    @PostMapping("/orders/cancel")
    public String cancel(Long orderId) {
        return "cancelled";
    }

    @PostMapping("/orders/status")
    public String status(Long orderId) {
        return "unknown";
    }

    @PostMapping("/orders/retry")
    public String retry(Long orderId) {
        return "retried";
    }

    @PostMapping("/orders/audit")
    public String audit(Long orderId) {
        return "audit";
    }

    public void handlePaid(Long orderId) {
        orderService.handlePaid(orderId);
    }

}
