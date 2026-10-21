# pythia-mssql

[English](README.md) · **Tiếng Việt**

pythia cho SQL Server: phát triển T-SQL cho AI agent, xây trên
[pythia-core](https://github.com/thaildhe172591/pythia-core). Nó nhắm làm
được điều mà [pythia](https://github.com/thaildhe172591/pythia) làm trên
Oracle và [pythia-postgres](https://github.com/thaildhe172591/pythia-postgres)
làm trên PostgreSQL: agent học từ catalog đang chạy, hỏi một người trước mọi
lần ghi, và chỉ ghi qua một cổng có snapshot, có kiểm chứng và báo cáo trung
thực.

**Alpha (0.1.1).** Nó đọc được mọi thứ mà nhịp Học của pythia cần, ghi qua
một cổng duy nhất, và chuẩn bị một project cho agent: guard, bản tóm tắt đầu
phiên, các cánh cửa duyệt và các skill `pythia-mssql-*`.

| Đã dùng được |
|---|
| đọc: `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` |
| ghi: `apply`, `deploy`, `approve`, `journal`, `history`, `policy`, `autopilot`, `lint` |
| harness: `install`, `doctor`, `hook`, `mcp`, `skill lint` |

Đã test trên SQL Server 2017, 2019, 2022 và 2025, mỗi bản qua toàn bộ live
check; 2017 là phiên bản tối thiểu, và thấp hơn thì `check` nói rõ (không
gì bị từ chối). SQL Server 2016 không có image Linux để test, và đã hết
extended support từ tháng 7/2026.

## Cài đặt

```bash
pip install pythia-mssql
```

Lệnh này kéo theo pythia-core, và [pymssql](https://pypi.org/project/pymssql/)
với các wheel mang sẵn FreeTDS: không cần cài ODBC driver nào, trên Windows,
macOS hay Linux. Bản đang phát triển là nhánh main của cả hai:

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-mssql"
```

## Chuẩn bị một project cho agent

```bash
cd your-project
pythia-mssql install     # once; a second run changes nothing
pythia-mssql doctor      # is everything wired? exit 1 names what is not
```

`install` ghi những thứ sau, và giữ nguyên mọi thứ khác:

- `.pythia/mssql/connections.json`, mode 600, tạo một lần từ template — dev
  tự điền mật khẩu; agent không bao giờ mở file này;
- các dòng `.gitignore` cho file đó, cho các lần duyệt của máy này
  (`.pythia/mssql/grants/`) và cho `.claude/settings.local.json`;
- `.claude/settings.local.json`: các hook (guard, bản tóm tắt đầu phiên,
  câu trả lời AskUserQuestion), ghi bằng đường dẫn tuyệt đối của interpreter
  này để chúng chạy được dù virtual environment có được kích hoạt hay không,
  và các deny rule cho file của engine;
- MCP approver `pythia_mssql` (tool `pythia_mssql_approve`), chỉ trong file
  riêng của máy này: local scope của Claude Code cho project
  (`~/.claude.json`) và `~/.codex/config.toml` của Codex, mỗi cái khi client
  đó đã từng chạy ở đây;
- một khối `pythia-mssql` trong CLAUDE.md và AGENTS.md (khối của các công cụ
  khác, và chữ của chính dev, được giữ nguyên);
- các skill, trong `.claude/skills` và `.agents/skills`:
  `using-pythia-mssql` (bộ định tuyến), `pythia-mssql-explore`,
  `pythia-mssql-impact`, `pythia-mssql-apply`, `pythia-mssql-deploy`,
  `pythia-mssql-autopilot`, `pythia-mssql-verify`.

Sau khi cài, khởi động lại phiên của agent để hook được nạp. Từ đó mỗi phiên
bắt đầu bằng các luật và một dòng `STATE` (connection, write policy). Trước
mỗi lần gọi tool, guard quyết định:

| Agent chạy | Guard |
|---|---|
| `sqlcmd`, `osql` hay `Invoke-Sqlcmd` được đưa SQL ghi (DDL, DML, `EXEC`, bất kỳ procedure `sp_` hay `xp_` nào, `SELECT ... INTO`, `NEXT VALUE FOR`, `:r`), một script (`-i`, `-InputFile`, `< file`, một pipe); `bcp ... in`; `sqlpackage` Publish hay Import — kể cả sau `docker exec`, `ssh`, `sudo` hay `bash -c` | chặn: mọi lần ghi đi qua `pythia-mssql apply` |
| một MCP SQL tool được đưa SQL ghi | chặn |
| đọc `connections.json`; sửa `policy.json`, journal hay một grant; đặt `PYTHIA_MSSQL_CI`; gọi `grants.mint` từ một one-liner | chặn |
| một lệnh đọc của `pythia-mssql`, một preview, `approve --card` | cho qua, không hỏi |
| `apply --confirm <token>` mà dev đã duyệt trên connection này | cho qua; apply kiểm lại |
| `sqlcmd` chỉ đọc, `bcp ... queryout`, `approve`, `--yes`, `policy set`, mọi lệnh ghép | đứng ngoài: client tự hỏi |

Guard đọc một lệnh theo những gì nó gọi tên, không theo ý nghĩa của nó: nó
có thể chặn một lệnh vô hại (một `SELECT` có nhắc tới `sp_help`) và bỏ lọt
một lần ghi được viết theo cách nó không liệt kê. Nó thấy các lệnh mà Claude
Code đưa cho tool Bash, không thấy SSMS hay Azure Data Studio. Cổng phía sau
vẫn giữ được trong cả hai trường hợp (SECURITY.md của pythia-core).

pythia-postgres và pythia-mongo cài cạnh nó trong cùng một project, và
pythia cho Oracle cũng vậy: mỗi bên giữ nguyên hook và khối hướng dẫn của
các bên khác, và guard cùng hook duyệt của mỗi bên chỉ hành động cho chính
công cụ của nó (CI của pythia-core kiểm tra điều này khi cả bốn cùng được
cài).

## Connection

`.pythia/mssql/connections.json` ở gốc project, chỉ chủ sở hữu được đọc
(`chmod 600`), và nằm ngoài git. Template:
[examples/connections.example.json](https://github.com/thaildhe172591/pythia-mssql/blob/main/examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 1433, "database": "app",
           "user": "app_agent", "password": "...", "schema": "app_owner",
           "encrypt": "request" }
}
```

- `host`, `database`, `user` là bắt buộc; chỉ dùng SQL Server
  authentication (một login và mật khẩu).
- `encrypt` là `off`, `request` (mặc định: TLS khi server có) hoặc
  `require`. FreeTDS không kiểm certificate của server.
- `schema` viết đúng như catalog viết (mặc định `dbo`). `check` cảnh báo khi
  default schema của login — nơi một tên không đủ định danh rơi vào — là một
  schema khác; đặt nó bằng `ALTER USER app_agent WITH DEFAULT_SCHEMA =
  app_owner`.
- Entry được chọn theo `--conn NAME`, rồi `PYTHIA_MSSQL_CONNECTION`, rồi
  entry duy nhất, rồi thư mục nằm ngay dưới gốc project, rồi `"default"`.
  `PYTHIA_MSSQL_CONFIG` trỏ tới một file khác.

pythia cho Oracle giữ `.pythia/connections.json`, pythia-postgres giữ
`.pythia/postgres/` và pythia-mongo giữ `.pythia/mongo/`; pythia-mssql không
đọc cái nào trong số đó.

## Các lệnh

```bash
pythia-mssql check                 # server, database, default schema drift
pythia-mssql ls "t_order%"         # objects by LIKE pattern
pythia-mssql src f_order_total     # a module's definition, SQL Server's line numbers
pythia-mssql cols t_order          # columns, types, defaults, identity, comments
pythia-mssql ddl t_order           # CREATE TABLE and its batches, rebuilt from the catalog
pythia-mssql grep "t_order where"  # every module line holding a text
pythia-mssql deps f_order_total    # what it references
pythia-mssql impact t_order        # what references it: run before changing it
pythia-mssql errors [NAME]         # every module bound now, as SQL Server would run it
```

`--json` cho một envelope mỗi lệnh; `--limit`, `--max-lines` và `--offset`
phân trang output dài, và mọi chỗ bị cắt đều nói cách lấy phần còn lại.

### Những gì catalog không thấy, và pythia-mssql nói ra thế nào

- **`impact` hỏi hai lần.** `sys.sql_expression_dependencies` ghi lại những
  gì mọi view, procedure, function và trigger tham chiếu tới — cả theo tên,
  khi object đó chưa tồn tại. Trigger trên một table và foreign key trỏ tới
  nó được thêm vào, và một check hay default constraint được tính là của
  table đó. Dynamic SQL (`EXEC` một chuỗi, `sp_executesql`) không có trong
  catalog: văn bản của module được tìm theo nguyên từ của tên, và các dòng
  đó được đánh dấu `[text]`. Các database khác và linked server không bao
  giờ được thấy. Mỗi điểm mù đều được in ra mỗi lần.
- **`errors` bind mọi module ngay bây giờ**, bằng
  `sys.dm_sql_referenced_entities`: một cột hay object bị thiếu gây ra đúng
  lỗi mà SQL Server sẽ báo khi module chạy. Một module chứa dynamic SQL được
  nêu tên là chưa kiểm bên trong các chuỗi của nó.
- **`ddl` của một table được dựng lại, không phải dump**, và kết thúc mỗi
  batch bằng `GO`; live check drop table, chạy DDL, dựng lại và so sánh.
  Generate Scripts của SSMS vẫn là chuẩn tham chiếu cho những gì nó chưa bao
  phủ.
- **Lệnh đọc không bao giờ commit.** SQL Server không có transaction chỉ
  đọc, nên mọi lệnh đọc chạy trong một transaction mà việc đóng connection
  sẽ rollback. Một login chỉ đọc (`db_datareader` cộng `VIEW DEFINITION`) là
  lớp bảo vệ đầu tiên.

### Ghi: cổng

```bash
pythia-mssql apply change.sql                   # preview: rehearsed, rolled back, nothing written
pythia-mssql approve 3fa9c1                     # the developer approves (or from chat, below)
pythia-mssql apply change.sql --confirm 3fa9c1  # writes it — only as approved
pythia-mssql journal restore <entry>            # undo is a write too: preview, approve, confirm
pythia-mssql policy                             # which groups may be written, and is rollback real?
```

Dev duyệt qua cánh cửa đầu tiên dùng được:

1. **Trong chat của Claude Code.** Agent hỏi bằng AskUserQuestion, nội dung
   đúng nguyên văn output của `pythia-mssql approve --card <token>`, hai lựa
   chọn Approve / Reject. Hook nhận câu trả lời chỉ ghi nhận lần duyệt khi
   câu hỏi mang đúng thẻ đó và chính dev chọn Approve — không phải câu trả
   lời do agent viết, không phải một hộp thoại tự đóng khi không có ai.
2. **Qua MCP approver** (`pythia_mssql_approve`; Codex bắt đầu từ đây):
   client hiện thẻ, và chỉ một lần Approve rõ ràng mới được tính.
3. **Ở console của dev:** `pythia-mssql approve <token>`.

`pythia-mssql doctor` cảnh báo những thiết lập có thể tự trả lời cánh cửa
chat thay cho dev (chế độ `dontAsk`, một allow rule cho AskUserQuestion, một
hook khớp mọi tool).

### Một release: `deploy`, một transaction

```bash
pythia-mssql deploy 01_schema.sql 02_data.sql                     # preview the release as one transaction
pythia-mssql deploy 01_schema.sql 02_data.sql --confirm 9c41e0b2aa  # all of it, as approved, or none
```

Một release — một hay nhiều script, được cắt ở đúng chỗ các công cụ của SQL
Server cắt: ở các dòng `GO`, rồi ở mỗi `;`, với thân của một module chạy tới
hết batch của nó — được rehearse trong một transaction: từng câu lệnh theo
thứ tự, snapshot trước khi chạy, số dòng và kết quả kiểm chứng lấy tại đúng
thời điểm của nó (một UPDATE trên cột mà chính release thêm vào được
rehearse với cột đó), rồi tất cả được rollback. Một thẻ hiện mọi câu lệnh,
và một lần duyệt (token 10 chữ số, qua cùng các cánh cửa) phủ cả release;
token của một câu lệnh lẻ không được duyệt riêng. Lúc confirm, nó kiểm từng
câu lệnh giống hệt từng byte với bản đã duyệt trước khi chạy gì, chạy lại
release trong một transaction, và chỉ commit nếu mọi câu lệnh vẫn khớp. Một
câu lệnh lỗi, hoặc dòng, object hay kết quả kiểm chứng đã thay đổi, sẽ
rollback cả release. Một trigger commit vượt qua rehearsal ở câu lệnh thứ *n*
được báo `WRITTEN?` cho các câu lệnh 1 tới *n*, kèm mọi lệnh restore. Bị từ
chối trước khi chạy gì: `GO n`, `SET` trong một release, và mọi thứ `apply`
từ chối.

### Lint: trước mọi lần apply

```bash
pythia-mssql lint 01_schema.sql 02_code.sql   # a change's files in one run
pythia-mssql lint --rules                     # every rule and its effective severity
```

Các rule đọc những gì SQL Server chấp nhận mà một người review thì không:

| Rule | Mặc định | Vì sao |
|---|---|---|
| `mssql-trigger-commit` | error | `COMMIT` của một trigger kết thúc transaction của người gọi (lỗi 3609), và commit cả phần việc mà người gọi có thể vẫn muốn rollback |
| `mssql-unsized-string` | error | `varchar`, `nvarchar`, `char`, `binary` không có độ dài chỉ chứa 1 ký tự khi khai báo và 30 trong `CAST`, và SQL Server cắt phần còn lại mà không báo |
| `mssql-nolock` | warn | `NOLOCK` / `READ UNCOMMITTED` có thể bỏ sót một dòng, đọc một dòng hai lần, hoặc đọc thứ đã bị rollback |
| `mssql-select-star` | warn | `SELECT *` trong một view giữ danh sách cột cũ cho tới khi `sp_refreshview`; `EXISTS (SELECT * ...)` thì không sao |
| `mssql-not-in-subquery` | warn | `NOT IN (SELECT ...)` không bao giờ đúng khi subquery trả về một NULL |
| `mssql-deprecated-type` | warn | `text`, `ntext`, `image` — dùng `varchar(max)`, `nvarchar(max)`, `varbinary(max)` |
| `mssql-datetime` | info | `datetime` làm tròn tới 1/300 s và `smalldatetime` tới phút — dùng `datetime2` |
| `mssql-sp-prefix` | warn | một procedure tên `sp_` được tìm trong master trước |
| `mssql-nocount` | info | một procedure không có `SET NOCOUNT ON` gửi số dòng sau mỗi câu lệnh |
| `mssql-table-comment` | warn | một table mới có `MS_Description` của nó trong cùng thay đổi |

Những gì SQL Server tự từ chối được để cho rehearsal. Team đặt severity và
quy ước đặt tên trong `.pythia/mssql/lint.json`:

```json
{"severity": {"mssql-select-star": "error", "naming": "error"},
 "naming": {"PROCEDURE": "^p_[a-z0-9_]+$", "VIEW": "^v_[a-z0-9_]+$"}}
```

Mọi preview đều hiện các phát hiện, lỗi của một câu lệnh nằm trên thẻ của
nó, và autopilot không bao giờ ghi một thay đổi còn lỗi lint.

### Autopilot: một lease thay cho từng lần duyệt

```bash
pythia-mssql autopilot request --groups source,comments --hours 2 --max-writes 30
pythia-mssql autopilot report      # every write under the lease, with its restore
pythia-mssql autopilot off         # anyone may revoke
```

Khi dev muốn agent làm việc mà không phải duyệt từng lần ghi, agent xin một
lease. Thẻ của nó nêu connection, các group, thời gian, số lần ghi và có gồm
câu lệnh phá hủy hay không, và chưa có gì được ủy quyền cho tới khi dev duyệt
nó qua một cánh cửa (hoặc tự chạy `pythia-mssql autopilot on` ở console).
Trong thời gian lease còn hiệu lực, `apply` và `deploy` ghi những gì nó phủ
mà không cần `--confirm` — vẫn có snapshot, rehearse, kiểm chứng và ghi
journal. Lease không bao giờ phủ một connection khác, một connection đánh
dấu `"protected": true` (hoặc có `"env"` là prod / production / prd /
live), một group hay câu lệnh phá hủy mà thẻ không nêu, hoặc quá 1000 dòng;
một lần ghi làm gãy thứ gì đó, một lần ghi thoát khỏi transaction của nó,
hoặc năm lần thất bại liên tiếp, sẽ tạm dừng nó.

### Một câu lệnh: `apply`

Mỗi file một câu lệnh. Một module (`CREATE [OR ALTER] PROCEDURE`,
`FUNCTION`, `VIEW`, `TRIGGER`) chiếm trọn batch của nó, như SQL Server vẫn
làm; mọi thứ khác kết thúc ở `;` của nó. `apply` xếp câu lệnh vào một group,
và policy quyết định: `source` và `comments` (một `MS_Description` qua
`sp_addextendedproperty`, `sp_updateextendedproperty` hay
`sp_dropextendedproperty`, với tham số có tên) cần dev duyệt; `data_dml`,
`structural` (DDL, `sp_rename`) và `grants` (`GRANT`, `REVOKE`, `DENY`,
user, role) bị từ chối cho tới khi dev chạy
`pythia-mssql policy set <group> confirm` ở console. `session` (`SET`) được
phép.

Preview hiện gì, và vì sao có thể tin nó:

- **Một rehearsal, không phải một dự đoán.** Câu lệnh đã chạy trong một
  transaction rồi được rollback. Mọi module phụ thuộc vào thứ đã thay đổi —
  và chính module đó — được bind bằng `sys.dm_sql_referenced_entities`
  trước và sau, và cái chỉ hỏng sau đó chính là cái câu lệnh đã làm gãy:
  một `ALTER TABLE ... DROP COLUMN` nêu tên view mà nó sẽ làm gãy. Diff so
  sánh định nghĩa trước và sau, cả hai theo cách SQL Server lưu chúng (nó
  lưu `CREATE OR ALTER` thành `create`, đệm thêm khoảng trắng).
- **Dòng được hiện ra và kiểm lại.** Một UPDATE hay DELETE được duyệt trên
  chính các dòng của nó: số lượng, một mẫu, và
  `CHECKSUM_AGG(BINARY_CHECKSUM(*))` trên chúng. Nếu có dòng nào thêm vào,
  rời đi hay thay đổi trước lúc confirm, lần confirm bị từ chối.
- **Confirm là cùng một rehearsal, chỉ commit nếu vẫn khớp.** Cùng token
  (file, object như lúc đó, các dòng), cùng số dòng, và không có gì gãy mà
  preview đã duyệt chưa hiện.
- **Một trigger không commit được rehearsal.** Trong SQL Server, `COMMIT`
  hay `ROLLBACK` của một trigger kết thúc transaction của người gọi. Câu
  lệnh chạy thấp hơn một mức transaction, nên một `COMMIT` duy nhất của
  trigger chỉ kết thúc mức đó và không commit gì (preview nói rõ: chạy theo
  bất kỳ cách nào khác, câu lệnh sẽ kết thúc với lỗi 3609). Nếu transaction
  vẫn kết thúc — một trigger commit hai lần, hoặc chạy vòng lặp —
  pythia-mssql đọc mọi trigger trong database: khi có một trigger có thể đã
  commit (nó có `COMMIT`, chạy code khác, hoặc không đọc được), hoặc không
  có gì thấy được giải thích chuyện đó, lần ghi được báo **`WRITTEN?`** với
  exit 3 kèm lệnh restore, không bao giờ là "không có gì được ghi". Chỉ một
  trigger rollback, khi không trigger nào có thể commit, mới là một lần từ
  chối bình thường.
- **Bị từ chối, kèm lý do:** `EXEC` một procedure, điều khiển luồng (`IF`,
  `WHILE`, `DECLARE`, `BEGIN ... END`), `SELECT`, `WITH`, `MERGE`, `USE`,
  lệnh điều khiển transaction, object tạm, login và các object cấp server
  khác, câu lệnh không chạy được trong transaction (`ALTER DATABASE`,
  `BACKUP`, full-text), extended property khác `MS_Description`, `GO`,
  nhiều câu lệnh trong một file (câu lệnh thứ hai trên dòng riêng cũng tính,
  có `;` hay không), một UPDATE hay DELETE mà không đọc trước được các dòng
  của nó (`TOP`, `OUTPUT`, `FROM` hay một join, một subquery, `WHERE CURRENT
  OF`, ngoặc không cân), và một module `WITH ENCRYPTION` (không có gì để
  snapshot).

Một rehearsal chờ lock tối đa 5 s (`SET LOCK_TIMEOUT`); SQL Server không có
statement timeout cho phiên. Nó vẫn kích hoạt trigger và lấy giá trị
`IDENTITY` cùng số của sequence, và preview của một câu lệnh DML nói rõ điều
đó. Exit code theo pythia: `0` sạch, `1` bị từ chối, `3` đã ghi nhưng gãy
(kèm lệnh restore).

### Quyền tối thiểu

Các lệnh đọc cần `db_datareader` trên database và `VIEW DEFINITION` (không
có nó, định nghĩa module đọc ra rỗng, và văn bản của mọi trigger không biết
được — nên một rehearsal kết thúc transaction của nó luôn được báo
`WRITTEN?`). Ghi cần đúng những gì câu lệnh cần: `db_datawriter` cho dòng,
`db_ddladmin` hoặc `ALTER` trên schema cho code và DDL. Preview cảnh báo khi
login là `sysadmin` hoặc `db_owner`. Live check chạy mọi lệnh đọc bằng một
login chỉ đọc, và mọi lần ghi bằng một login có `db_datawriter` và
`db_ddladmin`.

## Test

```bash
python tests/test_mssql.py    # no database, no pymssql — mutation-checked
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI chạy bộ test trên Ubuntu, Windows và macOS, Python 3.9 và 3.13, và live
check với SQL Server 2022 trong một service container. Nó test với nhánh
pythia-core cùng tên khi có.

## Giấy phép

MIT
