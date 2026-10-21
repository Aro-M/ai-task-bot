# Taskroom · AI Task Bot

[![CI](https://github.com/Aro-M/ai-task-bot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Aro-M/ai-task-bot/actions/workflows/ci.yml)

Telegram-ին գրում կամ ձայնային հաղորդագրություն ես ուղարկում, իսկ բոտը ստեղծում է առաջադրանք՝ վերնագրով, նկարագրությամբ, վերջնաժամկետով և առաջնահերթությամբ։ Առաջադրանքները տեսնում ու խմբագրում ես վեբ վահանակում։ Հայերենն ու անգլերենը մշակվում են նույն բոտով։

Սա մասնավոր տեխնիկական նախագծի իրականացում է։ Պահպանիր repository-ն ու հրապարակվող Docker images-ը մասնավոր։ Իրական բանալիները, անձնական ձայնագրությունները և բազայի պահուստային պատճենները GitHub չեն մտնում։

## Ինչ հնարավորություններ ունի

- Telegram-ի անձնական չաթից առաջադրանքի ստեղծում՝ տեքստով կամ ձայնով։
- OpenAI ռեժիմում՝ բնական խոսքից մեկ առաջադրանքի դաշտերի առանձնացում։ Ձայնը նախ վերածվում է տեքստի, հետո անցնում նույն task parser-ով, ինչ գրված հաղորդագրությունը։
- Առանձին վերնագիր, նկարագրություն, ժամկետ և ցածր/միջին/բարձր առաջնահերթություն։ Չնշված տվյալները պետք է մնան դատարկ։
- Ժամկետները լռելյայն Երևանի ժամանակով են (`Asia/Yerevan`, UTC+4)։ Կարող ես հստակ նշել այլ գոտի, օրինակ՝ UTC։ Բազայում ամսաթվերը պահվում են UTC-ով։
- Վահանակում՝ ստեղծում, խմբագրում, ջնջում, որոնում, ֆիլտրեր, տեսակավորում, էջավորում և ցուցակի/տախտակի տեսքեր։ Վիճակները՝ `To do`, `In progress`, `Completed`, ներառյալ ավարտվածի վերաբացում։
- Telegram-ից ստացված փոփոխությունները վահանակում թարմացվում են SSE կապով՝ առանց էջը ձեռքով թարմացնելու։
- Յուրաքանչյուր օգտատեր տեսնում է միայն իր տվյալները։ Մուտքը՝ Telegram-ի միանգամյա կոդով, ելք և հաշվի/տվյալների ջնջում։
- Ձայնային աշխատանքների հերթ, կրկնափորձեր, անհաջողության հաղորդագրություններ և նույն Telegram update-ից կրկնակի առաջադրանքի կանխում։
- Այլընտրանք՝ անվճար տեղային `whisper.cpp` ձայնաճանաչում և պարզ, դաշտանունների վրա հիմնված parser։

Մեկ հաղորդագրությունը ստեղծում է առավելագույնը մեկ առաջադրանք։ Բոտը գրանցում է գործողությունը․ այն չի զանգում մարդկանց, չի ուղարկում նամակներ, չի ամրագրում հանդիպումներ և ժամկետի պահին հիշեցում չի ուղարկում։ Վահանակի ինտերֆեյսը հիմնականում անգլերեն է, իսկ հայերեն առաջադրանքներն ու հայերեն ճանաչված ձայնի հաստատումները՝ հայերեն։

## 1. Ինչ է պետք նախապես

Հիմնական գործարկման համար պետք են՝

1. Telegram հաշիվ։
2. Git կամ GitHub Desktop՝ այս մասնավոր repository-ին հասանելիությամբ։
3. [Docker Desktop](https://www.docker.com/products/docker-desktop/)՝ Mac/Windows-ում, կամ Docker Engine + Compose plugin՝ Linux-ում։ Docker-ը պետք է գործարկված լինի։ Անհրաժեշտ է Compose **2.24.4+**։
4. OpenAI ռեժիմի համար՝ OpenAI API հաշիվ, վավեր API key և API վճարային հաշվեկշիռ։ Անվճար տեղային ռեժիմի համար դրանք պետք չեն։

Docker տարբերակում Python, Node.js, PostgreSQL կամ Redis առանձին տեղադրել պետք չէ։ Ստորև հրամանները նախատեսված են Mac/Linux կամ Windows-ի WSL2 միջավայրի համար։ Համակարգիչը քնած կամ անջատված լինելու դեպքում տեղային բոտը չի աշխատի։

Բացիր Terminal-ը և ներբեռնիր նախագիծը՝

```sh
git clone https://github.com/Aro-M/ai-task-bot.git
cd ai-task-bot
docker --version
docker compose version
```

Եթե նախագիծն արդեն համակարգչում կա, պարզապես մտիր նրա պանակը։ Հետագա հրամանները գործարկիր այդ պանակից։ Եթե private repository-ի մուտքը մերժվում է, նախ մուտք գործիր GitHub Desktop-ով կամ կարգավորիր GitHub-ի Git authentication-ը։

## 2. Ստեղծել Telegram բոտը

1. Telegram-ում բացիր պաշտոնական [@BotFather](https://t.me/BotFather)-ը։
2. Սեղմիր **Start**, ուղարկիր `/newbot`։
3. Ընտրիր ցուցադրվող անունը, հետո՝ եզակի username, որը վերջանում է `bot`-ով։
4. BotFather-ը կտա token։ Դա տեղադրելու ենք միայն քո տեղային `.env` ֆայլում՝ `TELEGRAM_BOT_TOKEN` դաշտում։
5. Բացիր նոր բոտի հղումը և սեղմիր **Start**։ Հավելվածը միացնելուց հետո այն կպատասխանի։

Միևնույն token-ով միաժամանակ մի գործարկիր երկու polling ծրագիր։ Տեղային աշխատանքը public URL, domain կամ HTTPS tunnel չի պահանջում․ ծրագիրն ինքն է Telegram-ից ստանում հաղորդագրությունները։

## 3. Ստեղծել և լրացնել `.env`-ը

**Միայն առաջին տեղադրման ժամանակ** պատճենիր նմուշը։ Եթե `.env` արդեն ունես, մի վերագրիր այն։

```sh
cp .env.example .env
chmod 600 .env
```

Բացիր `.env`-ը ցանկացած տեքստային խմբագրիչով։ Յուրաքանչյուր տող ունի `ԱՆՈՒՆ=արժեք` ձևը։ `.env.example`-ը հանրային ձևանմուշն է, `.env`-ը՝ քո գաղտնի տեղային կարգավորումը։

Գործարկիր հետևյալ հրամանը **երեք առանձին անգամ**, որպեսզի ստանաս բազայի գաղտնաբառ, `JWT_SECRET` և `WEBHOOK_SECRET`՝ իրարից տարբեր արժեքներով։ Ստացված արժեքները տեղադրիր համապատասխան դաշտերում։

```sh
openssl rand -hex 32
```

| Փոփոխական | Ինչ լրացնել |
|---|---|
| `ENVIRONMENT` | Տեղային գործարկման համար թող `development`։ |
| `POSTGRES_PASSWORD` | Առաջին պատահական արժեքը՝ բազայի գաղտնաբառ։ |
| `DATABASE_URL` | `postgresql+asyncpg://taskbot:ՆՈՒՅՆ_ԲԱԶԱՅԻ_ԳԱՂՏՆԱԲԱՌԸ@postgres:5432/taskbot`։ `postgres` անունը Docker ծառայությունն է, այն `localhost`-ով մի փոխարինիր։ |
| `REDIS_URL` | Թող `redis://redis:6379/0`։ |
| `JWT_SECRET` | Երկրորդ պատահական արժեքը՝ առնվազն 32 նիշ։ |
| `WEBHOOK_SECRET` | Երրորդ պատահական արժեքը։ Պահիր նաև polling ռեժիմում, որպեսզի հետո webhook-ը կարգավորելի լինի։ |
| `TELEGRAM_BOT_TOKEN` | Քո ստեղծած բոտի token-ը՝ BotFather-ից։ |
| `TELEGRAM_MODE` | Տեղային գործարկման համար՝ `polling`։ |
| `OPENAI_API_KEY` | Քո OpenAI API key-ը։ Պահանջվում է ստորև նշված հիմնական OpenAI ռեժիմում։ |
| `TASK_PARSER_ENABLED` | `true`՝ բնական խոսքից դաշտեր առանձնացնելու համար։ |
| `TASK_PARSER_MODEL` | Նախագծի ընթացիկ լռելյայն արժեքը՝ `gpt-6-luna`։ Հաշիվդ պետք է այդ մոդելին հասանելիություն ունենա։ |
| `WHISPER_MODEL` | Ընթացիկ հիմնական ձայնային մոդելը՝ `gpt-transcribe`։ Փոփոխականի անունը պատմական է։ |
| `WHISPER_LANGUAGE` | `auto`՝ հայերեն և անգլերեն ավտոմատ մշակելու համար։ Կարելի է հստակ ընտրել `hy` կամ `en`։ |
| `FRONTEND_ORIGIN` | Թող `http://localhost:8080` և վահանակը բացիր հենց այդ հասցեով։ |

OpenAI բանալի ստանալու համար քո հաշվով բացիր [API keys](https://platform.openai.com/api-keys) էջը, ընտրիր նախատեսված նախագիծը և ստեղծիր գաղտնի բանալի։ Այն պատճենիր միայն `OPENAI_API_KEY=`-ից հետո։ API-ի [վճարումները](https://platform.openai.com/settings/organization/billing/overview) առանձին են ChatGPT բաժանորդագրությունից։ Եթե նոր բանալի պետք չէ, օգտագործիր արդեն տեղադրված վավեր բանալին։ Բանալին մի ուղարկիր չաթով, մի նկարիր և մի տեղադրիր README-ում։

Բազայի համար hex գաղտնաբառը խուսափում է URL-ի հատուկ նշանների խնդրից։ Եթե օգտագործում ես այլ գաղտնաբառ, `DATABASE_URL`-ում հատուկ նշանները պետք է percent-encode անել։ Գոյություն ունեցող PostgreSQL volume-ի գաղտնաբառը միայն `.env`-ը խմբագրելով չի փոխվում․ պահիր գործող գաղտնաբառը կամ կատարիր առանձին բազայի գաղտնաբառի փոփոխություն։

### Սահմանաչափեր և վճարումներ

Նմուշում հետևյալ արժեքներն արդեն լրացված են․ սկզբում կարող ես թողնել դրանք։

| Փոփոխական | Լռելյայն արժեք / իմաստ |
|---|---|
| `MAX_AUDIO_DURATION_SEC`, `MAX_AUDIO_FILE_SIZE_MB` | 120 վայրկյան, 20 MiB՝ մեկ ձայնի համար։ |
| `MIN_AUDIO_DURATION_SEC` | 1 վայրկյան։ |
| `HOURLY_TRANSCRIPTION_LIMIT` | 500 ձայնային ընդունում՝ օգտատիրոջ վերջին 60 րոպեում։ |
| `DAILY_TRANSCRIPTION_LIMIT_PER_USER` | 500՝ օգտատիրոջ մեկ UTC օրում։ Օրը վերակայվում է Երևանի 04:00-ին։ |
| `MAX_CONCURRENT_JOBS_PER_USER` | Միաժամանակ 2 ակտիվ ձայնային աշխատանք։ |
| `GLOBAL_QUEUED_JOBS_LIMIT` | Ընդհանուր՝ 1,000 ակտիվ ձայնային աշխատանք։ |
| `GLOBAL_AI_REQUESTS_PER_MINUTE` | Նմուշում՝ 30 ընդհանուր AI հարցում/րոպե․ տեքստի parser-ն ու ձայնաճանաչումը կիսում են այն։ |
| `WHISPER_TIMEOUT_SEC`, `TRANSCRIPTION_JOB_TIMEOUT_SEC` | 45 վրկ՝ մեկ ձայնաճանաչման հարցման, 60 վրկ՝ ամբողջ ձայնային աշխատանքի համար։ |
| `WHISPER_MAX_RETRIES` | Անվանումը պատմական է․ 3 **ընդհանուր փորձ**, ոչ սկզբնականից բացի ևս 3։ |
| `WHISPER_RETRY_BACKOFF_BASE`, `WHISPER_RETRY_BACKOFF_MAX` | Կրկնափորձերի սպասման հիմքը՝ 2 վրկ, առավելագույնը՝ 30 վրկ։ |
| `TASK_PARSER_TIMEOUT_SEC` | 15 վրկ՝ առաջադրանքի դաշտերը ստանալու համար։ |
| `WORKER_CONCURRENCY` | 4 ձայնային worker process հիմնական ռեժիմում։ Տեղային AI overlay-ը օգտագործում է 1։ |
| `WHISPER_COST_PER_MINUTE` | Ծրագրի մոտավոր հաշվարկի գործակիցը՝ `$0.0045/րոպե`։ Տեղային AI-ում՝ 0։ |

Հին տեղադրումների `DAILY_TRANSCRIPTION_LIMIT` անունը նույնպես աշխատում է։ Ընտրիր մեկ անուն և հեռացրու կրկնօրինակը․ երկուսի առկայության դեպքում `DAILY_TRANSCRIPTION_LIMIT_PER_USER`-ը գերակայում է։ Չհաջողված ձայնային ընդունումներն էլ կարող են հաշվվել quota-ում։ Առանձին գործում է բոտի 60 հաղորդագրություն/րոպե/օգտատեր սահմանը։

**500 ձայնը դրամական սահման չէ։** OpenAI ռեժիմում տեքստը վճարովի parser է կանչում, ձայնը՝ նաև speech API։ 500 երկուրոպեանոց ձայնի մոտավոր տրանսկրիպցիան նշված գործակցով կլինի $4.50, դրան ավելանում է parser-ը և հնարավոր վճարովի կրկնափորձերը։ Գործակիցը չի փոխում մատակարարի գինը, իսկ ծրագիրը ընդհանուր դոլարային hard cap չունի։ Ստուգիր մատակարարի ընթացիկ [գները](https://openai.com/api/pricing/) և օգտագործումը․ spend alert-ը պարտադիր չէ, որ արգելափակի ծախսը։

## 4. Միացնել ծրագիրը՝ OpenAI ռեժիմ

`.env`-ը լրացնելուց հետո՝

```sh
docker compose up --build -d --wait
docker compose ps
```

Առաջին անգամ image-ների ներբեռնումն ու կառուցումը կարող են մի քանի րոպե տևել։ `migrate` ծառայությունը schema-ն ստեղծելուց հետո `Exited (0)` վիճակում լինելը նորմալ է։ Մնացած երկար աշխատող ծառայությունները պետք է գործարկված լինեն, իսկ healthcheck ունեցողները՝ healthy։

Բացիր [http://localhost:8080](http://localhost:8080)։ Telegram-ի քո բոտի անձնական չաթում ուղարկիր `/start`, հետո `/login`։ Բոտի տված 8-նիշ կոդը մուտքագրիր վահանակում։ Կոդը մեկանգամյա է և գործում է 5 րոպե։ Վեբ session-ը գործում է 15 րոպե, հետո պետք է նոր `/login` կոդ։

| Telegram հրաման | Ինչ է անում |
|---|---|
| `/start`, `/help` | Օգնություն և թելադրանքի օրինակներ։ |
| `/login` | Վեբ վահանակի մուտքի կոդ՝ միայն անձնական չաթում։ |
| `/tasks` | Վերջին առաջադրանքների կարճ ցանկը։ |
| Սովորական տեքստ կամ voice | Մեկ նոր առաջադրանք։ |

Ուղարկիր այս նախադասությունը՝ `Վաղը ժամը տասնչորսին զանգիր Աննային, որ քննարկենք զեկույցը։ Սա բարձր առաջնահերթություն ունի։`։ Սպասվող իմաստը՝ «Զանգել Աննային», նկարագրությունում՝ զեկույցի քննարկումը, վերջնաժամկետը՝ հաջորդ օրը Երևանի 14:00, առաջնահերթությունը՝ բարձր։ Բոտը կստեղծի նոր `To do` առաջադրանք, իսկ վահանակը կթարմացվի։ Վերնագրի բառացի ձևակերպումը AI ռեժիմում կարող է տարբեր լինել։

Այնուհետև նույն տեքստը արտասանիր Telegram voice-ով։ Ստուգիր առաջադրանքի բոլոր դաշտերը վահանակում․ գրված հաղորդագրության հաստատումը կարող է ցույց տալ միայն վերնագիրը, ձայնինը՝ նաև լրացված մյուս դաշտերը։ Վահանակի ձեռքով `New task` ձևը լրացվում է ուղղակիորեն և AI parser չի կանչում։

## 5. Անվճար տեղային տարբերակ

Սա օգտագործում է տեղային բազմալեզու `whisper.cpp base` մոդելը՝ OpenAI-ի փոխարեն։ `.env`-ում դեռ պետք են իրական Telegram token-ը, բազայի կարգավորումները և գաղտնի ստորագրման արժեքները։ OpenAI key պետք չէ։

```sh
docker compose -f docker-compose.yml -f docker-compose.local-ai.yml up --build -d --wait
```

Նույն հասցեն է՝ [http://localhost:8080](http://localhost:8080), նույն `/login` ընթացքով։ Overlay-ը բոլոր Python ծառայությունների համար ընտրում է տեղային speech endpoint, կեղծ տեղային key, զրոյական provider estimate և `TASK_PARSER_ENABLED=false`։ Այն չի խմբագրում քո `.env`-ը և OpenAI հարցումներ չի ուղարկում։ Production ռեժիմում այս overlay-ը չի օգտագործվում։

Առաջին մեկնարկը ներբեռնում է մոտ 141 MiB բազմալեզու մոդել և ստուգում checksum-ը։ Apple Silicon-ում ֆիքսված amd64 image-ն աշխատում է էմուլյացիայով և կարող է դանդաղ լինել։ **Հայերեն բնական խոսքի ճշտության երաշխիք չկա։** Այս ռեժիմի parser-ը պարզ կանոններ ունի․ ստորև բերված երկար խոսակցական օրինակների համար նախընտրիր OpenAI ռեժիմը։

Անվճար ռեժիմում առանձին դաշտերի համար օգտագործիր հստակ պիտակներ՝

> Վերնագիր Զանգել Աննային։ Նկարագրություն Քննարկել զեկույցը։ Վերջնաժամկետ վաղը ժամը տասնչորս։ Առաջնահերթություն բարձր։

> Title call Anna. Description discuss the report. Deadline tomorrow at six PM. Priority high.

Դրանք հիմնված են նախագծում օգտագործված հայերեն կառուցվածքային և անգլերեն ձայնային նմուշների վրա։ Հայերեն/անգլերեն պիտակները ճանաչվում են, բայց անվճար parser-ը չի փոխարինում բնական լեզվի AI-ին և կարող է սովորական խոսքը պահել որպես ամբողջական տեքստ։

Միայն անվճար իրական ձայնաճանաչումը ստուգելու համար, առանց `.env`, Telegram token-ի կամ OpenAI հաշվի՝

```sh
make test-local-ai
```

Այն գործարկում է առանձին `taskbot-local-ai-test` միջավայր, իրական մոդելով ճանաչում հանրային անգլերեն նմուշն ու սինթետիկ անգլերեն դաշտային թելադրանքը, հետո ստուգում worker → task → SSE → հաստատում շղթան։ Միայն Telegram-ի ցանցային կողմն է նմանակված։ Թեստային բազաները հեռացվում են, մոդելի cache volume-ը պահպանվում է։ Սա հայերենի ընդհանուր ճշտության չափում չէ։

## 6. Մի քանի նախադասությամբ թեստային տեքստեր՝ գրված և ձայնային փորձերի համար

Ստորև նոր, վերարտադրելի ձեռքով փորձարկման հավաքածու է՝ մեր օգտագործած «զանգել Աննային / քննարկել զեկույցը» օրինակի և նման առաջադրանքների հիման վրա։ Այն ավտոմատ անցած իրական speech benchmark չէ։ Կարճ օգտագործված նմուշները վերևում են, ավտոմատ parser-ի օրինակները՝ [ai_evaluation.json](tests/fixtures/ai_evaluation.json), իսկ իրական անգլերեն սինթետիկ ձայնը՝ [voice-fields.wav](tests/fixtures/voice-fields.wav)։

Յուրաքանչյուր հատվածը նախ ուղարկիր **մեկ տեքստային հաղորդագրությամբ**, հետո նույնը արտասանիր **մեկ voice-ով**։ Խոսիր բնական, փոքր դադարներով՝ մինչև 2 րոպե։ Փորձարկիր OpenAI ռեժիմում և համեմատիր իմաստը, բոլոր դաշտերն ու Երևանի ժամը։ Յուրաքանչյուր ուղարկում նոր առաջադրանք է ստեղծում, այնպես որ տեքստ/ձայն զույգից երկու առաջադրանք ստանալը սպասելի է։

### Հայերեն՝ 5 օրինակ

**HY-1 · համատեքստ և հստակ ժամկետ**

> Աննայի հետ երեկ զեկույցի մասին խոսեցինք, բայց թվերի հարցը բաց մնաց։ Ինձ համար առաջադրանք ավելացրու՝ զանգել Աննային։ Զանգը պետք է անեմ վաղը ժամը տասնչորսին՝ Երևանի ժամանակով։ Նկարագրության մեջ գրիր, որ պետք է քննարկենք զեկույցի վերջնական տարբերակն ու բաց մնացած թվերը։ Առաջնահերթությունը բարձր դիր։

Սպասվող՝ **զանգել Աննային**, նկարագրությունում՝ զեկույց/թվեր, **վաղը 14:00 Երևան**, **HIGH**։ Երեկվա խոսակցությունը ժամկետ չէ։

**HY-2 · մի քանի մանրամասներ նկարագրության մեջ**

> Պետք է պատրաստեմ հաճախորդի ամսական զեկույցը։ Նախորդ շաբաթվա տարբերակը միայն համեմատության համար է, դրա ամսաթիվը որպես վերջնաժամկետ մի վերցրու։ Նոր զեկույցի մեջ ներառիր վաճառքի թվերը և առանձին նշիր բաց հարցերը։ Այն ավարտելու ժամկետը վաղը երեկոյան ժամը տասնութն է։ Առաջնահերթությունը միջին է։

Սպասվող՝ **պատրաստել հաճախորդի ամսական զեկույցը**, նկարագրությունում՝ վաճառք/բաց հարցեր, **վաղը 18:00 Երևան**, **MEDIUM**։

**HY-3 · խոսքի ընթացքում ժամի ուղղում**

> Ավելացրու առաջադրանք՝ ստուգել մատակարարի հաշիվը։ Պետք է համեմատեմ գումարը պայմանագրի հետ և պարզեմ՝ հարկը ներառվա՞ծ է։ Սկզբում մտածում էի վաղը ժամը տասին անել, բայց փոխիր՝ վաղը ժամը տասնհինգն անց երեսունին։ Առաջնահերթությունը բարձր թող լինի։

Սպասվող՝ **ստուգել մատակարարի հաշիվը**, նկարագրությունում՝ պայմանագրի/հարկի ստուգում, վերջնական ժամկետը՝ **վաղը 15:30 Երևան**, **HIGH**։

**HY-4 · ժամկետը բացակայում է**

> Ուզում եմ առաջադրանք ավելացնել՝ կարգավորել աշխատանքային փաստաթղթերի պանակը։ Նկարագրության մեջ պահիր, որ կրկնվող ֆայլերը պետք է առանձնացնեմ, իսկ անհրաժեշտ պայմանագրերը՝ դասավորեմ ըստ հաճախորդների։ Սա ցածր առաջնահերթության գործ է։ Կոնկրետ օր կամ ժամ դեռ չեմ որոշել, այնպես որ վերջնաժամկետ մի նշանակիր։

Սպասվող՝ **կարգավորել աշխատանքային փաստաթղթերը**, նկարագրության մանրամասներ, **ժամկետը դատարկ**, **LOW**։

**HY-5 · առաջնահերթությունը բացակայում է**

> Վաղը ժամը տասնմեկին պետք է զանգեմ ատամնաբուժարան։ Ուզում եմ ճշտել ընդունելության ազատ ժամերը և խորհրդատվության արժեքը։ Սա պարզապես գրանցիր որպես առաջադրանք, որպեսզի չմոռանամ զանգը։ Առաջնահերթություն չեմ նշում։

Սպասվող՝ **զանգել ատամնաբուժարան**, նկարագրությունում՝ ազատ ժամեր/արժեք, **վաղը 11:00 Երևան**, **առաջնահերթությունը դատարկ**։ Բոտը զանգ կամ ամրագրում չի կատարում։

### English՝ 5 օրինակ

**EN-1 · supporting context and a deadline**

> Anna and I discussed the report yesterday, but we never resolved the missing figures. Add a task for me to call Anna tomorrow at two PM Yerevan time. Put the final report and the missing figures in the description. This is high priority.

Expected: **Call Anna**, description about the report/figures, **tomorrow 14:00 Yerevan**, **HIGH**. Yesterday is context, not the deadline.

**EN-2 · several description details**

> I need to prepare the monthly report for our client. Last week's version is only a reference, so don't use its date as the deadline. Include the sales numbers and list the unanswered questions separately. Please make the deadline tomorrow at six PM Yerevan time and set medium priority.

Expected: **Prepare the monthly client report**, sales/open questions in description, **tomorrow 18:00 Yerevan**, **MEDIUM**.

**EN-3 · a correction within the message**

> Create a task to review the supplier invoice. I need to compare the amount with the contract and check whether tax is included. I first thought tomorrow at ten AM, but change that to tomorrow at half past three in the afternoon, Yerevan time. Keep the priority high.

Expected: **Review the supplier invoice**, contract/tax details, final deadline **tomorrow 15:30 Yerevan**, **HIGH**.

**EN-4 · no deadline**

> Add a task to organize my work documents. Keep the instructions to separate duplicate files and arrange the necessary contracts by client in the description. This can be low priority. I haven't chosen a day or time yet, so leave the deadline empty.

Expected: **Organize work documents**, supporting instructions, **no deadline**, **LOW**.

**EN-5 · an explicit different timezone**

> Please add a task to send the revised proposal to David. Mention that it must include the updated prices and the delivery schedule. The deadline is tomorrow at ten AM UTC, not Yerevan time. I am not assigning a priority.

Expected: **Send the revised proposal to David**, prices/schedule in description, **tomorrow 10:00 UTC = 14:00 Yerevan**, **no priority**. The bot records the task; it does not send the proposal.

### Ինչպես հասկանալ՝ ճիշտ աշխատե՞ց

1. Ստեղծվե՞ց ճիշտ գործողության մեկ առաջադրանք՝ առանց համատեքստն ամբողջությամբ վերնագիր դարձնելու։
2. Նկարագրությունում մնացի՞ն կարևոր անուններն ու մանրամասները։
3. Ժամկետը և դրա ժամային գոտին ճի՞շտ են։ Չնշված ժամկետը դատա՞րկ է։
4. Առաջնահերթությունը ճի՞շտ է, իսկ չնշվածը՝ դատա՞րկ։
5. Տեքստային և ձայնային տարբերակների իմաստը համընկնո՞ւմ է։ AI-ի բառացի վերնագրերը պարտադիր չէ, որ նույնը լինեն։

Եթե գրված տարբերակը ճիշտ է, իսկ ձայնինը՝ սխալ, հավանական պատճառը ձայնաճանաչումն է, բայց այդ համեմատությունը միայնակ լիարժեք ախտորոշում չէ։ Մոդելը կարող է սխալ լսել անունը, ժամը կամ առաջնահերթությունը։ Լռությունից կամ անհասկանալի խոսքից առաջադրանք չպետք է ստեղծվի։ OpenAI ռեժիմում պարզ բարևը կամ միայն տեղեկատվական հարցը նույնպես առաջադրանք չեն։

## 7. Ինչպես է աշխատում ներսում

```mermaid
flowchart TD
    U[Telegram օգտատեր] --> B[aiogram բոտ / FastAPI]
    B -->|Տեքստ| P[Task parser]
    B -->|Ձայնի metadata և ընդունում| J[(PostgreSQL job + outbox)]
    J --> D[Outbox dispatcher / scheduler]
    D --> Q[Redis / Celery հերթ]
    Q --> W[Ձայնային worker]
    W --> A[Ներբեռնում և ffmpeg ստուգում]
    A --> S[OpenAI gpt-transcribe կամ տեղային whisper.cpp]
    S -->|Տրանսկրիպցիա| P
    P -->|OpenAI gpt-6-luna կամ տեղային կանոններ| T[(PostgreSQL task + outbox)]
    T --> D
    D -->|Հաստատում| U
    D --> E[Redis օգտատիրոջ event]
    E --> API[FastAPI / authenticated SSE]
    API --> UI[Next.js վահանակ / Nginx]
    UI -->|CRUD / session cookie| API
    API --> T
```

- **Տեքստը** բնական լեզվից դառնում է վավերացված task։ OpenAI ռեժիմի այս քայլը provider հարցում է կատարում ingestion-ի ընթացքում։
- **Ձայնը** սկզբում գրանցվում է որպես աշխատանք և հերթագրվում․ երկար ձայնաճանաչումը կատարվում է առանձին worker-ում։ Speech մոդելը խոսքը դարձնում է տեքստ, task parser-ը՝ դաշտեր։ Դրանք տարբեր աշխատանքներ են։
- **PostgreSQL**-ը պահում է օգտատերերը, առաջադրանքները, աշխատանքի վիճակները և durable outbox-ը։ **Redis/Celery**-ն կազմակերպում են հերթն ու event-ները։
- Task-ն ու նրա event/հաստատման մտադրությունը պահպանվում են միասին։ Նույն update/job-ի կրկնակի մշակումը նոր task չպետք է ստեղծի։ Telegram ծանուցումը ցանցային անորոշ խափանումից հետո կարող է կրկնվել։
- Ժամանակավոր ձայնային ֆայլերը հեռացվում են մշակումից հետո։ Առանձին ամբողջական transcript չի պահվում։ OpenAI ռեժիմում ձայնն ու task-ի տեքստը փոխանցվում են OpenAI-ին։

| Պանակ | Նպատակ |
|---|---|
| `app/` | API, բոտ, parser, ձայն, worker, մոդելներ, անվտանգություն։ |
| `frontend/` | Next.js/React/TypeScript վահանակ, Nginx և բրաուզերային թեստեր։ |
| `migrations/` | Alembic բազայի schema փոփոխություններ։ |
| `services/` | API/bot/worker Dockerfile-ներ՝ ընդհանուր Python base-ից։ |
| `tests/`, `scripts/` | Մեկուսացված թեստեր, գնահատում, օպերացիոն գործիքներ։ |
| `.github/workflows/` | CI, առանձին հաստատվող image publication և deployment։ |

## 8. Դադարեցնել, թարմացնել և գտնել խնդիրները

```sh
# Կարգավիճակ և վերջին log-եր
docker compose ps
docker compose logs --tail=80 api bot worker dispatcher scheduler

# Դադարեցնել․ առաջադրանքները պահպանվում են Docker volumes-ում
docker compose down

# Կոդի կամ .env-ի փոփոխությունից հետո նորից գործարկել
docker compose up --build -d --wait

# Առողջություն և ամբողջական պատրաստություն
curl --fail http://localhost:8080/api/health
curl --fail http://localhost:8080/api/health/ready

# Անձնական տվյալներ չցուցադրող ընդհանուր օպերացիոն ցուցանիշներ
docker compose exec -T api python -m scripts.metrics
```

Անվճար ռեժիմում նույն `up/down/ps/logs` հրամաններին ավելացրու `-f docker-compose.yml -f docker-compose.local-ai.yml`։ Հիմնական ռեժիմին վերադառնալու համար գործարկիր հիմնական `docker compose up --build -d --wait` հրամանը․ այն վերաստեղծում է հիմնական Python ծառայությունները `.env` կարգավորումներով։ Տեղային speech container-ը կարող է մնալ անգործուն, մինչև տեղային overlay-ի `down`-ը։

**Իրական տվյալների համար `docker compose down -v` մի գործարկիր**․ `-v`-ը ջնջում է volumes-ը և բազայի առաջադրանքները։ Պահուստային պատճենների ու վերականգնման ընթացքը նկարագրված է [deployment ուղեցույցում](docs/deployment.md)։

| Խնդիր | Ստուգել / լուծում |
|---|---|
| Docker daemon-ը հասանելի չէ | Միացրու Docker Desktop-ը և սպասիր engine-ի պատրաստ լինելուն։ |
| 8080 port-ը զբաղված է | Դադարեցրու այդ port-ը զբաղեցնող ծրագիրը։ Եթե փոխում ես frontend host port-ը, համապատասխան փոխիր նաև `FRONTEND_ORIGIN`-ը։ |
| Բոտը չի պատասխանում | Ստուգիր իրական token-ը, ինտերնետը, `TELEGRAM_MODE=polling`-ը, bot/dispatcher/scheduler ծառայությունները և որ այլ poller չի աշխատում։ |
| 401 կամ invalid API key | Համոզվիր՝ key-ը տեղադրված է հենց `.env`-ում, մոդելին հասանելիություն կա, ապա վերագործարկիր ծառայությունները։ Բանալին log-ում մի ցուցադրիր։ |
| Insufficient quota / billing / 429 | Ստուգիր OpenAI API balance-ը, model permissions-ը և rate limits-ը։ ChatGPT Plus-ը API credit չէ։ Հավելվածի 500 սահմանը provider-ի սահմանը չի բարձրացնում։ |
| `Your voice transcription limit has been reached` | Ստուգիր երկու transcription quota-ները, ընդունումների քանակը և օրական UTC պատուհանը։ `.env`-ը փոխելուց հետո վերաստեղծիր bot/worker/api ծառայությունները հիմնական `up` հրամանով։ |
| `Please wait for your current voice tasks` | Սպասիր ակտիվ երկու ձայների ավարտին․ սա առանձին concurrency սահման է։ |
| Տեքստը չի մշակվում՝ key-ի բացակայության պատճառով | OpenAI ռեժիմում լրացրու key-ը կամ ընտրիր անվճար overlay-ը։ Միայն `WHISPER_MODEL` փոխելը անվճար ռեժիմ չի միացնում։ |
| Ձայնից անունը/ժամը սխալ է | Նույնը փորձիր տեքստով, խոսիր մաքուր ձայնով, նշիր ժամը և պիտակները։ Բոտի կամ վահանակի դաշտերը ստուգիր և անհրաժեշտության դեպքում խմբագրիր։ |
| Վահանակ մուտքը չի ստացվում / 403 | Բացիր հենց `FRONTEND_ORIGIN` հասցեն, մի խառնիր `localhost` և `127.0.0.1`, նոր `/login` կոդ վերցրու։ |
| Բազայի գաղտնաբառը սխալ է | `DATABASE_URL`-ի և սկզբում ստեղծված volume-ի գաղտնաբառերը պետք է համընկնեն։ Volume-ը ջնջելը տվյալների կորուստ է։ |
| Հին task-ը չի երևում | Ստուգիր մուտք գործած Telegram հաշիվը, որոնումը, ֆիլտրերը և էջավորումը։ |

### Եթե նախկինում webhook էր գրանցված

Polling-ը չի ջնջում webhook-ը լուռ։ Եթե բոտի log-ը հայտնում է այդ հակասության մասին և որոշել ես անցնել polling-ի, **մեկ անգամ** գործարկիր սա․ պահպանվում են սպասող Telegram updates-ը։

```sh
docker compose exec -T bot python - <<'PYTHON'
import asyncio
from aiogram import Bot
from app.config import settings

async def main():
    async with Bot(settings.telegram_bot_token) as bot:
        await bot.delete_webhook(drop_pending_updates=False)

asyncio.run(main())
PYTHON
```

Հետո նորից գործարկիր հավելվածը։ Public production տեղադրման համար անհրաժեշտ են HTTPS domain/reverse proxy և `TELEGRAM_MODE=webhook`․ ամբողջ քայլերը՝ [docs/deployment.md](docs/deployment.md)։

## 9. Ծրագրավորողի տեղադրում և ավտոմատ ստուգումներ

Հիմնական հավելվածը Docker-ով աշխատեցնելու համար այս բաժնի գործիքները պետք չեն։ Թեստերի համար տեղադրիր Python **3.12**, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js **22**, npm, `make`, ffmpeg/ffprobe և Docker։ Mac-ում ffmpeg-ը կարելի է տեղադրել `brew install ffmpeg`-ով, Ubuntu-ում՝ `sudo apt-get install ffmpeg`-ով։

```sh
make install
cd frontend
npx playwright install chromium firefox webkit
cd ..
make lint
make test-unit
make test-integration
make test-e2e
make test-e2e-live
make test-security
make test-containers
make test-mutations
uv run python -m scripts.evaluate_ai
```

Linux-ում browser system dependencies-ի համար օգտագործիր `npx playwright install --with-deps chromium firefox webkit`։ `make test-e2e-live`-ը գործարկում է առանձին `taskbot-qa` stack-ը 18080/18081 port-երով, ժամանակավոր բազայով, առանց իրական բանալիների։ Կատարում է DB/Redis խափանման և API-ի IP-ի փոփոխության փորձեր, հետո Chromium/Firefox/WebKit թեստեր։ Այն չի փոփոխում հիմնական տեղային տվյալները։

`make ci`-ն միավորում է հիմնական ստուգումները և Docker builds-ը։ GitHub-ի [CI workflow-ը](.github/workflows/ci.yml) նաև ստուգում է repository-ի պատմությունը գաղտնիքների համար և պահում է հաշվետվությունները Actions artifacts-ում։ Իրական AI ճշտությունը չի ապացուցվում նմանակված HTTP պատասխաններով։ Հայերեն speech-ի լայն, պիտակավորված գնահատման հավաքածու դեռ չկա։

## Հաշվետվություն և մանրամասն ուղեցույցներ

- [Ընթացիկ ստուգման հաշվետվություն և պատրաստ լինելու սահմաններ](VERIFICATION.md)։
- [Թեստավորման ռազմավարություն](TESTING.md) և [թեստերի ցանկ](TEST_INVENTORY.md)։
- [Ճարտարապետություն](docs/architecture.md), [AI-ի աշխատանքը](docs/ai-design.md), [անվտանգություն](docs/security.md)։
- [Production տեղադրում և վերականգնում](docs/deployment.md), [ինժեներական պայմանագիր](CONTRACT.md), [չափված benchmark-եր](BENCHMARKS.md)։

GitHub push-ը թարմացնում է կոդն ու միացնում CI-ն։ Այն ինքնաբերաբար public server deployment կամ վճարովի API փորձարկում չի կատարում։ Առանձին release/deploy workflow-ները պահանջում են նախապես կարգավորված մասնավոր registry, GitHub Environments, թույլտվություններ և համապատասխան server runner-ներ։
