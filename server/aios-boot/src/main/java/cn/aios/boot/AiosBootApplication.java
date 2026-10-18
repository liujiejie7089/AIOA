package cn.aios.boot;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * AIOS 后端启动类：扫描 cn.aios 下所有模块。
 */
@SpringBootApplication(scanBasePackages = "cn.aios")
@MapperScan("cn.aios.**.mapper")
@EnableScheduling
public class AiosBootApplication {

    public static void main(String[] args) {
        SpringApplication.run(AiosBootApplication.class, args);
    }
}
