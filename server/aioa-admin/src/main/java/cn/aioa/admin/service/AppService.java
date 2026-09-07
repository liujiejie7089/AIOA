package cn.aioa.admin.service;

import cn.aioa.admin.entity.AppRegistry;
import cn.aioa.admin.mapper.AppRegistryMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 应用注册表查询。M1 不细查权限（enabled 即可见），M3 接入 permission_code 过滤。
 */
@Service
public class AppService {

    private final AppRegistryMapper appRegistryMapper;

    public AppService(AppRegistryMapper appRegistryMapper) {
        this.appRegistryMapper = appRegistryMapper;
    }

    public List<AppRegistry> enabledApps() {
        return appRegistryMapper.selectList(new LambdaQueryWrapper<AppRegistry>()
                .eq(AppRegistry::getEnabled, true)
                .orderByAsc(AppRegistry::getSort));
    }

    public AppRegistry byCode(String appCode) {
        return appRegistryMapper.selectOne(new LambdaQueryWrapper<AppRegistry>()
                .eq(AppRegistry::getAppCode, appCode));
    }
}
