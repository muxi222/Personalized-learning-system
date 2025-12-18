# 批改记录查询调试指南

## 问题：点击学科后看不到批改记录

### 快速诊断步骤

#### 1. 检查数据库中的数据

```bash
# 查看所有批改记录和对应用户
sqlite3 data/sqlite/app.db "
SELECT 
  ec.id,
  ec.user_id,
  u.username,
  ec.subject,
  ec.exam_title
FROM exam_corrections ec
LEFT JOIN users u ON ec.user_id = u.id
ORDER BY ec.created_at DESC;
"
```

**当前数据**：
```
7|2|zhang|MATH|math试卷批改
6|2|zhang|MATH|math试卷批改
5|2|zhang|MATH|math试卷批改
4|2|zhang|OTHER|other试卷批改
```

**结论**：所有记录属于 user_id=2 (zhang用户)

#### 2. 检查当前登录用户

**方法A：浏览器控制台**
```javascript
// 在浏览器 DevTools > Console 运行
const authStorage = localStorage.getItem('auth-storage')
if (authStorage) {
  const { state } = JSON.parse(authStorage)
  console.log('当前用户:', state.user)
  console.log('User ID:', state.user?.id)
}
```

**方法B：API请求**
```bash
# 获取token
TOKEN=$(在浏览器Network面板复制)

# 查询当前用户信息
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"
```

#### 3. 查看后端日志

重启后端并查看日志输出：

```bash
# 重启后端
pkill -f uvicorn
uvicorn backend.main:app --reload

# 然后在前端点击"数学"学科卡片
# 查看终端输出的日志：
```

**期望日志**：
```
INFO: list_corrections called: user_id=X, user=username, subject=math
INFO: get_exam_corrections: user_id=X, subject=math
INFO: Filtering by subject: math (lowercase: math)
INFO: Subject filter matched: math -> MATH
INFO: Query result: found N corrections (total=N)
```

**如果看到**：
```
INFO: Query result: found 0 corrections (total=0)
```

可能原因：
- **user_id 不匹配**：登录用户不是zhang (user_id=2)
- **学科匹配失败**：枚举转换有问题

### 解决方案

#### 方案1：使用正确的用户登录

如果所有批改记录属于zhang用户，需要：

**选项A：用zhang账号登录**
```
用户名: zhang
密码: (zhang注册时设置的密码)
```

**选项B：让longpasstest用户也有批改记录**
```
1. 用longpasstest登录
2. 访问 /exam-upload
3. 上传一张试卷
4. 等待批改完成
5. 再访问 /corrections
```

#### 方案2：临时测试（修改数据库）

**仅用于测试**，将现有记录转移给当前登录用户：

```bash
# 假设当前登录用户是 user_id=1
sqlite3 data/sqlite/app.db "
UPDATE exam_corrections SET user_id = 1;
UPDATE questions SET user_id = 1;
"
```

#### 方案3：检查API端点

**测试无筛选查询**（应该返回所有记录）：
```bash
curl "http://localhost:8000/api/v1/corrections/?page=1&page_size=12" \
  -H "Authorization: Bearer $TOKEN"
```

如果这个也返回空，确认是user_id问题。

**测试有筛选查询**：
```bash
curl "http://localhost:8000/api/v1/corrections/?page=1&page_size=12&subject=math" \
  -H "Authorization: Bearer $TOKEN"
```

### 调试检查清单

- [ ] 数据库中有exam_corrections记录
- [ ] 记录的user_id与当前登录用户一致
- [ ] 后端日志显示正确的user_id
- [ ] subject筛选逻辑匹配成功（MATH vs math）
- [ ] 查询返回非空结果

### 常见问题

**Q: 统计显示有批改次数，但列表为空？**

A: 统计API和列表API使用相同的user_id。如果统计显示有数据，说明：
- 统计API工作正常
- 列表API的筛选条件有问题（可能是subject筛选）

**解决办法**：
1. 不传subject参数，先看能否返回记录
2. 检查后端日志中的subject匹配信息
3. 确认数据库subject值是 MATH 还是 math

**Q: 前端显示"数学批改: 4次"，但点击后列表为空？**

A: 这说明：
- 统计查询找到了4条MATH记录
- 列表查询with subject=math筛选失败

**调试**：查看后端日志中的：
```
Subject filter matched: math -> MATH
```

如果看不到这条日志，说明枚举匹配失败。

---

## 快速修复命令

```bash
# 1. 确认当前登录用户
# 在浏览器控制台运行
JSON.parse(localStorage.getItem('auth-storage')).state.user

# 2. 查看该用户的批改记录
sqlite3 data/sqlite/app.db "
SELECT COUNT(*) 
FROM exam_corrections 
WHERE user_id = X;  -- 替换X为用户ID
"

# 3. 如果为0，上传一张试卷创建记录
# 或者临时修改现有记录的user_id（仅测试）

# 4. 重启后端查看日志
pkill -f uvicorn
uvicorn backend.main:app --reload

# 5. 在前端操作，观察后端日志输出
```

