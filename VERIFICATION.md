# Ստուգման հաշվետվություն · 22 հոկտեմբերի 2026

[![CI](https://github.com/Aro-M/ai-task-bot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Aro-M/ai-task-bot/actions/workflows/ci.yml)

## Գնահատական

**Տեղային օգտագործման և մասնավոր staging-ի հիմնական ծրագրային ուղիները ստուգված են։ Public production թողարկման ամբողջական հաստատում դեռ չկա։** Վերարտադրելի ստուգումները ստորև են, իսկ hosted CI-ի ընթացիկ արդյունքը՝ վերևի badge-ի ու [Actions](https://github.com/Aro-M/ai-task-bot/actions/workflows/ci.yml) էջի միջոցով։ CI-ի հաջողությունը պետք է համադրել հենց հետաքրքրող commit SHA-ի հետ․ այս փաստաթղթի առկայությունը CI-ի հաջողություն չի նշանակում։

Անգլերեն երկու իրական տեղային ձայնային նմուշներն անցել են։ Հայերեն/անգլերեն բնական խոսքի լայն ճշտությունը և README-ի տասը երկար ձեռքով փորձարկման օրինակները չեն ներկայացվում որպես չափված հաջողության տոկոս։ Գրված և ձայնից ստացված տեքստի AI parser-ը նույնն է, բայց speech մոդելը կարող է արդեն իսկ սխալ տեքստ փոխանցել նրան։

## Հինգ հիմնական հոսքերը

| Հոսք | Ստուգված արդյունք | Ապացույցի սահմանը |
|---|---|---|
| Telegram տեքստ → task → հաստատում → event → վահանակ | Անցել է | Իրական PostgreSQL/Redis/Celery/SSE, նմանակված Telegram և AI ցանցային եզրեր։ |
| Telegram voice → անմիջական պատասխան → հերթ → worker → speech → task → հաստատում/SSE | Անցել է | Provider contract-ի service թեստեր և երկու առանձին իրական տեղային անգլերեն inference թեստ։ Voice provider-ը չի կանչվում Telegram handler-ում։ |
| Վահանակի status փոփոխություն → PATCH → DB → event | Անցել է | Unit, իրական API և Chromium/Firefox/WebKit բրաուզերային ճանապարհներ։ |
| Worker/provider խափանում → սահմանափակ retry/backoff → վերջնական անվտանգ արդյունք | Անցել է | Timeout/429/5xx, retry/TTL/dead-letter, replay/եզակիություն, infra recovery և mutation ստուգումներ։ Կենդանի մատակարարի խափանում չի առաջացվել։ |
| Docker Compose startup → migrations → healthy ծառայություններ → աշխատող վահանակ | Անցել է | Հիմնական տեղային stack-ը վերակառուցվել է, readiness-ը՝ 200։ Անձնական բազայի volumes-ը պահպանված են։ |

## Թեստերի և գործիքների արդյունքները

| Ստուգում | Այս ստուգման արդյունք |
|---|---|
| Backend unit/security/audio/parser/deployment | **274 անցած**, 0 ձախողված։ |
| PostgreSQL/Redis/Celery/SSE և service E2E | **20 անցած**։ 2 տեղային speech case-երը այստեղ բաց են թողնվում և առանձին գործարկվել են։ |
| React/API/Երևանի ժամային փոխակերպումներ | **18 անցած**։ |
| Exact Next hydration script CSP | **1 անցած**։ |
| Desktop/mobile Chromium | **8 անցած**։ |
| Իրական stack՝ Linux Chromium/Firefox/WebKit | **3 անցած**, ներառյալ CRUD, tenant isolation, live events, axe և layout ստուգումներ։ |
| Իրական տեղային speech՝ հանրային նմուշ + սինթետիկ դաշտային թելադրանք | **2 անցած**՝ առանց վճարովի AI հարցման։ |
| Deterministic fallback extraction | **17/17 fixture**։ Սա AI մոդելի բնական լեզվի ճշտության չափում չէ։ |
| Անվտանգության/ամբողջականության targeted mutations | **8/8 հայտնաբերված**՝ սովորական test assertion failure-ով։ |
| DB/Redis pause, վերականգնում, ընդունված գրառումների պահպանում, API նոր IP | **8/8 օպերացիոն ստուգում**։ |
| Ruff / Black / mypy | Անցել են։ |
| ESLint / Prettier / TypeScript | Անցել են։ |
| pip-audit / npm audit | Հայտնի կախվածության խոցելիություն չի հայտնաբերվել այդ պահին։ |
| Bandit՝ high severity | Անցել է։ |
| Hadolint՝ հինգ Dockerfile | Անցել է։ |
| Trivy lock-file HIGH/CRITICAL scan | Հայտնաբերված խոցելիություններ՝ 0։ Սա base image OS scan չէ։ |
| Next production export / Docker service builds | Անցել են։ |
| Git diff whitespace / տեղային Markdown հղումներ | Անցել են։ |

**324 սովորական case configuration + 2 opt-in իրական տեղային speech case = 326**։ Այս թիվը ներառում է parameterization-ն ու տարբեր browser project-ներով կրկնությունները, ոչ 326 անկախ product flow։ 17 extraction fixture-ը, 8 mutation և 8 operational ստուգումները լրացուցիչ են։ Կրկնակի գործարկումները նոր թեստեր չեն հաշվվում։ Անուններն ու հրամանները՝ [TEST_INVENTORY.md](TEST_INVENTORY.md)։

### Coverage

- Backend՝ **91.27%** համակցված line/branch coverage, պահանջվող նվազագույնը՝ 80%։ XML-ում՝ 1,321/1,425 line և 341/396 branch։
- Frontend՝ **95.47% line**, **90.45% branch**։ Նոր `dateTime.ts`-ը ներառված է coverage-ի չափման մեջ։
- Coverage-ը չի ապացուցում, որ բոլոր հնարավոր մուտքերն ու իրական speech դեպքերը ճիշտ են մեկնաբանվում։

### macOS-ի սահմանափակում

Native macOS իրական-stack suite-ում Chromium-ը և WebKit-ն անցել են, իսկ Firefox-ը չի մեկնարկել՝ `sandbox_extension_issue_file_to_process ... Operation not permitted` և launch timeout պատճառով։ Սա չի ներկայացվել որպես անցած թեստ։ Նույն երեք browser project-ները հետագայում ամբողջությամբ անցել են **Playwright v1.58.2 Linux image-ում**։ Վերարտադրելու հրամանները [TESTING.md](TESTING.md)-ում են։ GitHub CI-ն օգտագործում է native Linux engines։

## Այս թարմացմամբ ուղղված խնդիրները

1. Հին README/AI/architecture/security նկարագրությունները այլևս չէին համընկնում կոդի հետ՝ OpenAI parser, նոր speech contract, Երևանի ժամային գոտի և 500 quota։ Դրանք համադրվել են իրական իրականացման հետ։
2. `gpt-transcribe`-ի multipart/languages պատասխանի փոփոխությունից հետո legacy whisper.cpp/whisper-1 ուղիները չունեին իրենց պատասխանի ճիշտ մշակում։ Վերականգնվել է legacy contract-ը՝ լեզվի/segment-ի վավերացմամբ և regression թեստերով։ Երկու իրական տեղային inference case-ն անցել են։
3. Գլոբալ test fixture-ը դատարկում էր key-ը և խափանում mocked speech-ի ու անվճար իրական speech-ի ստուգումները։ Այն այժմ միշտ դնում է անվտանգ test-only key, իսկ live task parser-ը մնում է անջատված, եթե թեստը հատուկ չի ընտրում նմանակված provider։ Անձնական բանալին թեստերը չեն ժառանգում։
4. Speech service E2E fixture-ները և local voice ժամկետի assertion-ները թարմացվել են համապատասխանաբար նոր provider contract-ին և Երևանի ժամին։
5. Նախորդ hosted CI-ն կանգնել էր QA-ի հին API IP-ը reserve անելու Docker քայլում։ Disposable QA ցանցն այժմ ունի explicit subnet, և դրա deterministic parser-ը հստակ անջատում է paid AI կախվածությունը։ API replacement-ի ստուգումն անցել է տեղային երկու միջավայրում։
6. `dateTime.ts`-ը դուրս էր frontend coverage include-ից։ Այն ավելացվել է, և malformed local date-ի վավերացման դեպքը ստուգվում է։
7. Backend Docker context-ից այժմ ճիշտ բացառվում են նաև live browser-ի report/trace պանակները։
8. Առաջին նոր hosted run-ում (`b6bbafd`, [39679425343](https://github.com/Aro-M/ai-task-bot/actions/runs/39679425343)) բոլոր երեք իրական-stack browser թեստերն անցել են, բայց workflow-ը ձախողվել է հետագա cleanup-ում․ `cd frontend`-ը փոխում էր EXIT trap-ի աշխատանքային պանակը, և այն չէր գտնում `tests/fixtures/qa.env`-ը։ Make target-ը browser քայլն այժմ գործարկում է subshell-ում, որպեսզի cleanup-ը կատարվի repository root-ից և պահպանի թեստի իրական exit status-ը։ Վերջնական CI-ի արդյունքը ստուգվում է նոր commit-ի run-ով։

README-ում ավելացված են BotFather-ից սկսվող տեղադրում, `.env`-ի լրացում, API billing-ի և quota-ի տարբերություն, հիմնական/անվճար ռեժիմներ, Telegram login, թարմացում/դադարեցում, խափանման լուծումներ, architecture Mermaid և 5 հայերեն + 5 անգլերեն երկար manual acceptance տեքստ՝ սպասվող դաշտերով։

## Ֆայլերի մաքրում և գաղտնի տվյալներ

Հեռացվել են կրկնվող/հնացած `AUDIT.md`, `REVIEW.md`, `IMPLEMENTATION.md`, `docs/testing.md` և հին `docs/architecture.svg`-ը։ Դրանց արդիական տեղեկությունը պահվում է README-ում, այս հաշվետվությունում և թեմատիկ փաստաթղթերում։ Ճարտարապետության տեսողական սխեմայի մեկ աղբյուրը հիմա README-ի Mermaid-ն է։ Թեստերի fixture-ներն ու կիրառվող scripts-ը պահպանվել են։

`.env`, կախվածությունները, build output-ը, թեստերի reports/traces-ը, model caches-ը, ձայնագրություններն ու backup dump-երը Git-ignored են։ Դրանք չեն ուղարկվում GitHub։ Սովորական տեղային PostgreSQL/Redis volumes-ը և օգտատիրոջ առաջադրանքները չեն ջնջվել։ Վճարովի speech/Responses թեստ այս ընթացքի ընթացքում չի կատարվել։

Secret scan-ը CI-ում կատարվում է commit history-ի համար՝ redacted Gitleaks-ով։ Push-ից առաջ կատարվում է նաև staged փոփոխությունների ստուգում։ Մանրամասն հում արդյունքները պահվում են տեղային ignored `reports/`-ում, hosted արդյունքները՝ համապատասխան CI run-ի artifacts-ում։

## Գործող ծրագրի smoke ստուգումներ

- Վահանակ՝ HTTP **200**։
- `/api/health/ready`՝ HTTP **200**, configuration validated, PostgreSQL/Redis/workers՝ ok։
- Առանց session-ի `/api/tasks`՝ HTTP **401**։
- Telegram `getMe`՝ իրական բոտի token-ը վավերացված է։
- OpenAI model catalog՝ `gpt-transcribe` և `gpt-6-luna` համար HTTP **200**։ Սա հաստատում է key-ի/model visibility-ն, ոչ վճարովի inference-ի որակը կամ billing-ի բավարարությունը։
- API, bot, worker, dispatcher, frontend, PostgreSQL և Redis՝ healthy, scheduler-ը՝ running։
- Սա միայն տեղային հասանելիություն է․ public HTTPS/webhook deployment տեղի չի ունեցել այս ստուգմամբ։

## Ինչ է մնում public production թողարկումից առաջ

1. Կենդանի հայերեն/անգլերեն պիտակավորված ձայնագրություններով ստուգել անունները, ժամերը, բարդ խոսքը, վերջնական դաշտերը և իրական վճարումները։ README-ի տասը օրինակներն օգտագործել որպես ձեռքով acceptance հավաքածու։
2. Production domain/TLS/Telegram webhook-ը կարգավորել և ստուգել իրական server-ում։ GitHub push-ը deployment չէ։
3. Կատարել backup-ի իրական restore rehearsal առանձին staging միջավայրում և ստուգել վերականգնված տվյալները։
4. Սկանավորել հենց թողարկվող images-ի OS packages-ը թարմ vulnerability database-ով, ոչ միայն dependency locks-ը։
5. Ստուգել անհրաժեշտ ծանրաբեռնվածքը, disk/memory/queue դիտարկումը, alert-ները և GitHub release/deploy environments-ի թույլտվությունները։ Տեքստային AI parsing-ը ingestion-ի ընթացքում է, ուստի բարձր latency/ծավալի դեպքում polling throughput-ը պետք է առանձին չափել։

**Ստուգված ծրագրային ճանապարհները բավարար են տեղային աշխատանքի և վերահսկվող մասնավոր փորձարկման համար։ Լայն speech ճշտության կամ public production ամբողջական պատրաստության երաշխիք չի տրվում։**
