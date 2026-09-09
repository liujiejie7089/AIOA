package cn.aioa.boot;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * AIOA 后端启动类：扫描 cn.aioa 下所有模块。
 */
@SpringBootApplication(scanBasePackages = "cn.aioa")
@MapperScan("cn.aioa.**.mapper")
@EnableScheduling
public class AioaBootApplication {

    public static void main(String[] args) {
        SpringApplication.run(AioaBootApplication.class, args);
    }
}
