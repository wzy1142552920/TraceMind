package com.example.order;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface OrderMapper {
    @Select("SELECT status FROM orders WHERE id = #{orderId}")
    String findStatus(Long orderId);

    default boolean exists(Long orderId) {
        return findStatus(orderId) != null;
    }

    @Update("UPDATE orders SET status = #{status} WHERE id = #{orderId}")
    default int updateStatus(Long orderId, String status) {
        return 0;
    }
}
