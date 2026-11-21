"""English translations. Keys are the Persian source strings passed to ``app.i18n.tr``."""

EN = {
    '\n\n**ابزار Qwen: {name}**':
        '\n\n**Qwen tool: {name}**',
    '\n**HTML داخل کد بالا:**':
        '\n**HTML inside the code above:**',
    '\n**خروجی ابزار:**':
        '\n**Tool output:**',
    'گفت‌وگوی جدید':
        'New chat',
    'با تطبیق تقریبی (فاصله‌ها نادیده گرفته شد)':
        'With a fuzzy match (whitespace ignored)',
    'مسیر نامعتبر است':
        'Invalid path',
    'مسیر خالی یا نامعتبر است':
        'Empty or invalid path',
    'مسیر مطلق مجاز نیست: {rel}':
        'Absolute paths are not allowed: {rel}',
    'مسیر خالی است':
        'Path is empty',
    'مسیر خارج از پوشهٔ پروژه است: {rel}':
        'Path is outside the project folder: {rel}',
    'نام فایل نامعتبر است: {rel}':
        'Invalid file name: {rel}',
    'تغییر پوشهٔ .git مجاز نیست':
        'Changing the .git folder is not allowed',
    'SEARCH خالی است':
        'SEARCH is empty',
    'متن SEARCH در فایل {count} بار پیدا شد؛ مبهم است و اعمال نشد':
        'The SEARCH text was found {count} times in the file; it is ambiguous and was not applied',
    'متن SEARCH در فایل پیدا نشد (حتی با نادیده‌گرفتن فاصله‌ها)':
        'The SEARCH text was not found in the file (even ignoring whitespace)',
    'متن SEARCH با نادیده‌گرفتن فاصله‌ها {v0} جا پیدا شد؛ مبهم است و اعمال نشد':
        'Ignoring whitespace, the SEARCH text was found in {v0} places; it is ambiguous and was not applied',
    'بلوک ناتمام ماند (پاسخ قطع شد)':
        'The block was left unfinished (the reply was cut off)',
    'بدون تغییر':
        'No change',
    'بلوک SEARCH/REPLACE معتبری پیدا نشد':
        'No valid SEARCH/REPLACE block found',
    'فایلی برای حذف وجود ندارد':
        'There is no file to delete',
    '{path} یک فایل است':
        '{path} is a file',
    '{path} در این فاصله ساخته شده است؛ دوباره بررسی کنید':
        '{path} was created in the meantime; please review again',
    '{path} پس از پیشنهاد تغییر کرده است؛ دوباره بررسی کنید':
        '{path} changed after the proposal; please review again',
    '{path} دیگر وجود ندارد':
        '{path} no longer exists',
    '{path} یک پوشه است':
        '{path} is a folder',
    'فایل بیش از حد بزرگ است':
        'The file is too large',
    'فایل وجود ندارد و SEARCH خالی نیست':
        'The file does not exist and SEARCH is not empty',
    'فایل متنی UTF-8 نیست؛ تغییر آن پشتیبانی نمی‌شود':
        'Not a UTF-8 text file; changing it is not supported',
    'position نامعتبر: {pos} (start یا end)':
        'Invalid position: {pos} (start or end)',
    '{label} «{marker}» پیدا نشد':
        '{label} “{marker}” not found',
    '{label} «{marker}» در {v0} خط پیدا شد (خطوط {v1})؛ مبهم است':
        '{label} “{marker}” found on {v0} lines (lines {v1}); it is ambiguous',
    'start (شمارهٔ خط) یا start_marker لازم است':
        'start (a line number) or start_marker is required',
    'شمارهٔ خطوط با start_marker {delta:+d} جابه‌جا شد':
        'Line numbers shifted by {delta:+d} using start_marker',
    'فقط یکی از to_line / after / before را بدهید':
        'Give only one of to_line / after / before',
    'حذف خطوط {v0}-{e}':
        'Delete lines {v0}-{e}',
    'جایگزینی خطوط {v0}-{e}':
        'Replace lines {v0}-{e}',
    'text خالی است':
        'text is empty',
    'محتوای {src} درج شد':
        'Inserted the contents of {src}',
    'pattern خالی است':
        'pattern is empty',
    'expected_count={exp} اما {total} مورد پیدا شد؛ چیزی تغییر نکرد ({report})':
        'expected_count={exp} but {total} matches were found; nothing changed ({report})',
    '{total} مورد بیشتر از max_count={mx} است؛ چیزی تغییر نکرد':
        '{total} matches exceed max_count={mx}; nothing changed',
    'هیچ موردی پیدا نشد؛ چیزی تغییر نکرد':
        'No matches found; nothing changed',
    'مسیر وجود ندارد: {src}':
        'Path does not exist: {src}',
    'مقصد نمی‌تواند خود مبدأ یا داخل آن باشد':
        'The destination cannot be the source itself or inside it',
    'کپی از {a}':
        'Copied from {a}',
    'منتقل‌شده از {a}':
        'Moved from {a}',
    'patch هیچ فایلی ندارد (--- / +++ لازم است)':
        'The patch contains no files (--- / +++ required)',
    'start/end باید شمارهٔ خط باشند':
        'start/end must be line numbers',
    'بازهٔ خطوط {start}-{end} در {rel} نامعتبر است (فایل {n} خط دارد)':
        'Line range {start}-{end} in {rel} is invalid (the file has {n} lines)',
    'خط {e} در {rel} شامل end_marker «{em}» نیست؛ ابتدا read_file بگیرید':
        'Line {e} in {rel} does not contain end_marker “{em}”; call read_file first',
    'to_line={n} نامعتبر است (فایل {v0} خط دارد)':
        'to_line={n} is invalid (the file has {v0} lines)',
    '{rel} یک پوشه است':
        '{rel} is a folder',
    '{rel} فایل متنی UTF-8 نیست':
        '{rel} is not a UTF-8 text file',
    'فایل وجود ندارد: {rel}':
        'File does not exist: {rel}',
    '{rel} از قبل وجود دارد؛ بازنویسی با فایل باینری پشتیبانی نمی‌شود':
        '{rel} already exists; overwriting with a binary file is not supported',
    '{rel} یک فایل است':
        '{rel} is a file',
    '{what} خطوط {a}-{b} درون فایل':
        '{what} lines {a}-{b} within the file',
    'درج متن':
        'Insert text',
    'regex نامعتبر: {e}':
        'Invalid regex: {e}',
    'path یا glob لازم است':
        'path or glob is required',
    'بیش از {MAX_REPLACE_FILES} فایل تغییر می‌کند؛ glob را محدودتر کنید':
        'More than {MAX_REPLACE_FILES} files would change; narrow the glob',
    'جایگزینی متن ({v0} مورد)':
        'Replace text ({v0} matches)',
    'پوشه بیش از {MAX_PATH_FILES} فایل دارد':
        'The folder has more than {MAX_PATH_FILES} files',
    '{b} از قبل وجود دارد (برای بازنویسی "overwrite": true)':
        '{b} already exists (use "overwrite": true to overwrite)',
    'منتقل شد به {b}':
        'Moved to {b}',
    'بازه پس از جابه‌جایی با start_marker از فایل بیرون می‌زند':
        'After shifting with start_marker the range falls outside the file',
    'end_marker «{em}» بعد از start_marker پیدا نشد':
        'end_marker “{em}” not found after start_marker',
    'to_line باید عدد باشد':
        'to_line must be a number',
    'مقصد داخل همان بازه‌ای است که جابه‌جا می‌شود':
        'The destination is inside the range being moved',
    '{v0} خط از {v1}':
        '{v0} lines from {v1}',
    '{v0} خط به {dst} منتقل شد':
        'Moved {v0} lines to {dst}',
    ' (فایل تازه)':
        ' (new file)',
    'replacement نامعتبر: {e}':
        'Invalid replacement: {e}',
    'hunk @@ -{v0} در {rel} با محتوای فعلی جور نیست؛ ابتدا read_file بگیرید':
        'hunk @@ -{v0} in {rel} does not match the current content; call read_file first',
    '{new} از قبل وجود دارد':
        '{new} already exists',
    'فایل تازه از patch':
        'New file from patch',
    'حذف با patch':
        'Deleted by patch',
    'از {old} (patch)':
        'From {old} (patch)',
    'تغییر نام به {new}':
        'Renamed to {new}',
    'indent باید عدد، "auto" یا رشتهٔ فاصله باشد':
        'indent must be a number, "auto" or a whitespace string',
    'جابه‌جایی':
        'Move',
    'کپی':
        'Copy',
    'سرآیند hunk نامعتبر: {v0}':
        'Invalid hunk header: {v0}',
    'hunk @@ -{v0} در {rel} مبهم است (چند جا جور است)':
        'hunk @@ -{v0} in {rel} is ambiguous (matches in several places)',
    'فایل باینری ({v0:,} بایت)':
        'Binary file ({v0:,} bytes)',
    'پوشهٔ تازه':
        'New folder',
    'ابزار ویرایش ناشناخته: {name}':
        'Unknown edit tool: {name}',
    'C#: namespace‌ها به مسیر وابسته نیستند و تغییری نکردند.':
        'C#: namespaces do not depend on paths and were not changed.',
    'Python: importهای نسبی (from . import) بررسی نشدند.':
        'Python: relative imports (from . import) were not checked.',
    'Java: مسیر {old} با package {pkg} جور نیست؛ تغییری داده نشد.':
        'Java: path {old} does not match package {pkg}; nothing was changed.',
    'Java: {new} بیرون از ریشهٔ سورس است؛ package تغییر نکرد.':
        'Java: {new} is outside the source root; package not changed.',
    'Java: نام کلاس {oc} به {nc} تغییر نکرد؛ در صورت نیاز جداگانه ویرایش کنید.':
        'Java: class name {oc} was not renamed to {nc}; edit it separately if needed.',
    'Go: go.mod پیدا نشد؛ import pathها تغییر نکردند.':
        'Go: go.mod not found; import paths were not changed.',
    'به‌روزرسانی {n} ارجاع (import/require/include)':
        'Update {n} references (import/require/include)',
    'Go: فقط بخشی از بستهٔ {v0} جابه‌جا شد؛ import pathها تغییر نکردند.':
        'Go: only part of package {v0} was moved; import paths were not changed.',
    'ابزار ناشناخته: {raw_name}':
        'Unknown tool: {raw_name}',
    'بلوک ابزار ناتمام ماند':
        'The tool block was left unfinished',
    'پوشه وجود ندارد: {v0}':
        'Folder does not exist: {v0}',
    'هیچ فایلی پیدا نشد (no files matched).':
        'No files matched.',
    'چیزی پیدا نشد (no matches).':
        'No matches.',
    'path لازم است':
        'path is required',
    '{rel} یک تصویر است؛ از image_info استفاده کنید.':
        '{rel} is an image; use image_info.',
    'فایل خیلی بزرگ است ({v0}); از search استفاده کنید.':
        'The file is too large ({v0}); use search.',
    'هیچ فایل متنی پیدا نشد':
        'No text files found',
    '{rel}: قالب تصویر شناخته نشد ({v0})':
        '{rel}: unrecognised image format ({v0})',
    'فقط نشانی http یا https معتبر پذیرفته می‌شود':
        'Only valid http or https URLs are accepted',
    'متد نامعتبر: {method}':
        'Invalid method: {method}',
    '{rel} از قبل وجود دارد؛ بازنویسی نشد (برای بازنویسی "overwrite": true).':
        '{rel} already exists; not overwritten (use "overwrite": true to overwrite).',
    'command خالی است':
        'command is empty',
    'ابزارهای ویرایش در پنل بازبینی اجرا می‌شوند':
        'Edit tools run in the review panel',
    'ابزار ناشناخته: {name}':
        'Unknown tool: {name}',
    'پوشهٔ پروژه در دسترس نیست':
        'The project folder is not available',
    'آرگومان‌ها باید یک شیء JSON باشند':
        'Arguments must be a JSON object',
    '{rel} در تغییرات پیشنهادیِ در انتظار بررسی حذف شده است.':
        '{rel} is deleted in the pending proposed changes.',
    '{rel} فایل متنی UTF-8 نیست (باینری یا کدگذاری دیگر).':
        '{rel} is not a UTF-8 text file (binary or another encoding).',
    'درخواست ناموفق بود: {v0}':
        'Request failed: {v0}',
    'دانلود متوقف شد':
        'Download stopped',
    'دانلود ناموفق بود: {v0}':
        'Download failed: {v0}',
    'اجرای فرمان ممکن نشد: {e}':
        'Could not run the command: {e}',
    'مسیر رد شد: {e}':
        'Path rejected: {e}',
    'خطای ابزار: {name__}: {e}':
        'Tool error: {name__}: {e}',
    '(نام از نشانی)':
        '(name from URL)',
    '(خواندن ممکن نشد)':
        '(could not read)',
    'فایل بزرگ‌تر از {v0} است':
        'The file is larger than {v0}',
    'آرگومان‌ها JSON معتبر نیستند':
        'Arguments are not valid JSON',
    'در ارتباط با {name} خطایی رخ داد. جزئیات فنی در گزارش تشخیصی ثبت شده است.':
        'An error occurred while talking to {name}. Technical details were written to the diagnostic log.',
    '\n\nپاسخ سرور: {detail}':
        '\n\nServer response: {detail}',
    'توکن دستی Qwen که در تنظیمات ذخیره شده منقضی شده است (اعتبار توکن‌های وب Qwen فقط حدود ۱۵ دقیقه است). آن را در تنظیمات حذف کنید و از ورود در مرورگر داخلی استفاده کنید.':
        'The manual Qwen token saved in Settings has expired (Qwen web tokens are only valid for about 15 minutes). Remove it in Settings and sign in with the built-in browser instead.',
    'ورود Qwen در مرورگر داخلی منقضی شده و صفحه نتوانست آن را تازه کند. در پنجرهٔ مرورگر داخلی دوباره وارد شوید و «ادامه» را بزنید.':
        'The Qwen sign-in in the built-in browser has expired and the page could not refresh it. Sign in again in the built-in browser window and press “Continue”.',
    'Qwen در منطقهٔ شما در دسترس نیست (سایت chat.qwen.ai این IP را مسدود کرده است). برای استفاده باید VPN سراسری (System-wide) روشن باشد.':
        'Qwen is not available in your region (chat.qwen.ai blocked this IP). A system-wide VPN must be on to use it.',
    'دیوار امنیتی Qwen (Alibaba WAF) تأیید مرورگر یا کپچا خواسته است. در پنجرهٔ «مرورگر داخلی Qwen» تأیید یا کپچا را خودتان کامل کنید، «ادامه» را بزنید و پیام را دوباره بفرستید. برنامه کپچا را حل نمی‌کند.':
        'Qwen\'s security wall (Alibaba WAF) asked for a browser check or captcha. Complete it yourself in the “Qwen built-in browser” window, press “Continue” and send the message again. The app does not solve captchas.',
    'در مرورگر داخلی وارد حساب Qwen نشده‌اید. در پنجرهٔ باز‌شده وارد chat.qwen.ai شوید، «ادامه» را بزنید و پیام را دوباره بفرستید.':
        'You are not signed in to Qwen in the built-in browser. Sign in to chat.qwen.ai in the window that opened, press “Continue” and send the message again.',
    'مرورگر داخلی به Qwen دسترسی پیدا نکرد (اتصال یا VPN را بررسی کنید، یا شاید صفحهٔ تأیید باز شده باشد). پنجرهٔ مرورگر داخلی را ببینید و دوباره تلاش کنید.':
        'The built-in browser could not reach Qwen (check your connection or VPN, or a verification page may be open). Look at the built-in browser window and try again.',
    'صفحهٔ Qwen در مرورگر داخلی در میانهٔ درخواست دوباره بارگذاری شد. پس از بارگذاری کامل chat.qwen.ai دوباره تلاش کنید.':
        'The Qwen page in the built-in browser reloaded in the middle of the request. Try again once chat.qwen.ai has fully loaded.',
    'مرورگر داخلی روی سایت chat.qwen.ai نیست. در پنجرهٔ مرورگر داخلی به chat.qwen.ai برگردید و دوباره تلاش کنید.':
        'The built-in browser is not on chat.qwen.ai. Go back to chat.qwen.ai in the built-in browser window and try again.',
    'مرورگر داخلی نتوانست chat.qwen.ai را بارگذاری کند. اتصال و VPN را بررسی کنید.':
        'The built-in browser could not load chat.qwen.ai. Check your connection and VPN.',
    'Qwen در مهلت تعیین‌شده پاسخی نداد. شاید مرورگر داخلی منتظر ورود یا تأیید شما باشد؛ پنجرهٔ آن را ببینید و دوباره تلاش کنید.':
        'Qwen did not respond in time. The built-in browser may be waiting for you to sign in or verify; check its window and try again.',
    'مرورگر داخلی (QtWebEngine) در این نسخهٔ برنامه در دسترس نیست. در تنظیمات روش اتصال HTTP را انتخاب کنید یا برنامه را دوباره بسازید.':
        'The built-in browser (QtWebEngine) is not available in this build. Choose the HTTP connection method in Settings or rebuild the app.',
    'Qwen دسترسی را رد کرد (HTTP 403). در مرورگر داخلی وارد شوید یا تأیید را کامل کنید.':
        'Qwen denied access (HTTP 403). Sign in or complete the verification in the built-in browser.',
    'Qwen به‌جای داده یک صفحهٔ وب برگرداند؛ احتمالاً ورود یا تأیید لازم است. پنجرهٔ مرورگر داخلی را ببینید.':
        'Qwen returned a web page instead of data; signing in or verification is probably required. Check the built-in browser window.',
    'ادامهٔ پاسخ ناقص برای Qwen پشتیبانی نمی‌شود؛ یک پیام پیگیری بفرستید.':
        'Continuing a cut-off reply is not supported for Qwen; send a follow-up message.',
    'Qwen مدل انتخاب‌شده را نپذیرفت. در تنظیمات مدل دیگری انتخاب کنید یا فهرست مدل‌ها را به‌روز کنید.':
        'Qwen did not accept the selected model. Choose another model in Settings or refresh the model list.',
    'این گفت‌وگو دیگر روی Qwen وجود ندارد. گفت‌وگو را پاک کنید یا گفت‌وگوی تازه‌ای آغاز کنید.':
        'This conversation no longer exists on Qwen. Clear it or start a new chat.',
    'پاسخ {name} بدون متن پایان یافت. ممکن است درخواست مسدود شده یا رابط خصوصی تغییر کرده باشد.':
        'The {name} reply ended without any text. The request may have been blocked or the private API may have changed.',
    'زمینهٔ گفت‌وگو از سوی {name} پذیرفته نشد (HTTP 422). شناسهٔ پیام قبلی یا ساختار درخواست را بررسی کنید.':
        '{name} did not accept the conversation context (HTTP 422). Check the previous message ID or the request structure.',
    'نشست Qwen نامعتبر یا منقضی شده است. در مرورگر داخلی دوباره وارد شوید (یا توکن دستی را در تنظیمات به‌روز کنید)، «ادامه» را بزنید و پیام را دوباره بفرستید.':
        'The Qwen session is invalid or expired. Sign in again in the built-in browser (or update the manual token in Settings), press “Continue” and send the message again.',
    'توکن نشست {name} نامعتبر یا منقضی شده است. آن را در تنظیمات به‌روز کنید.':
        'The {name} session token is invalid or expired. Update it in Settings.',
    'تعداد درخواست‌ها از حد مجاز {name} گذشته است. کمی صبر کنید.':
        'Too many requests to {name}. Please wait a little.',
    'تأیید Cloudflare لازم است. در وب‌سایت {name} وارد شوید و دوباره تلاش کنید.':
        'Cloudflare verification is required. Sign in on the {name} website and try again.',
    'اتصال شبکه برقرار نشد یا مهلت درخواست پایان یافت.':
        'Could not connect to the network, or the request timed out.',
    'اتصال هنگام دریافت پاسخ قطع شد.':
        'The connection dropped while receiving the reply.',
    'سرویس {name} در دسترس نیست. بعداً تلاش کنید.':
        'The {name} service is unavailable. Try again later.',
    'پاسخ ساخت نشست، شناسهٔ معتبر ندارد. شاید رابط خصوصی {name} تغییر کرده باشد.':
        'The session-creation response has no valid ID. The {name} private API may have changed.',
    'شناسهٔ پیام قبلی نامعتبر است. گفت‌وگوی تازه‌ای آغاز کنید.':
        'The previous message ID is invalid. Start a new chat.',
    'توکن نشست Qwen در تنظیمات وارد نشده است.':
        'No Qwen session token has been entered in Settings.',
    'Qwen درخواست را رد کرد. متن پاسخ سرور در زیر آمده است.':
        'Qwen rejected the request. The server response is shown below.',
    'پاسخ {name} با ساختار شناخته‌شده سازگار نیست. شاید رابط خصوصی تغییر کرده باشد.':
        'The {name} reply does not match the known format. The private API may have changed.',
    'تنظیمات':
        'Settings',
    'سرویس گفت‌وگوهای تازه':
        'Service for new chats',
    'وضعیت':
        'Status',
    'برای نگه‌داشتن توکن فعلی، خالی بگذارید':
        'Leave empty to keep the current token',
    'توکن نشست وب DeepSeek':
        'DeepSeek web session token',
    'حذف توکن DeepSeek ذخیره‌شده':
        'Remove saved DeepSeek token',
    'مرورگر داخلی (پیشنهادی)':
        'Built-in browser (recommended)',
    'HTTP مستقیم با توکن (ممکن است با کپچا مسدود شود)':
        'Direct HTTP with a token (may be blocked by captcha)',
    'روش اتصال':
        'Connection method',
    'ورود / تأیید Qwen در مرورگر داخلی':
        'Sign in / verify Qwen in the built-in browser',
    'مدل':
        'Model',
    'بررسی اتصال Qwen و دریافت فهرست مدل‌ها':
        'Check the Qwen connection and fetch the model list',
    'توکن دستی':
        'Manual token',
    'اختیاری؛ با مرورگر داخلی لازم نیست. خالی = توکن فعلی':
        'Optional; not needed with the built-in browser. Empty = current token',
    'توکن Qwen (اختیاری)':
        'Qwen token (optional)',
    'نمایش متن توکن تایپ‌شده':
        'Show typed token text',
    'حذف توکن Qwen ذخیره‌شده':
        'Remove saved Qwen token',
    'سرویس‌ها':
        'Services',
    'روشن':
        'Light',
    'تیره':
        'Dark',
    'پوسته':
        'Theme',
    'اندازهٔ قلم':
        'Font size',
    'قلم برنامه «وزیرمتن» است (مجوز SIL Open Font License 1.1) و همراه برنامه نصب می‌شود.':
        'The app font is “Vazirmatn” (SIL Open Font License 1.1) and ships with the app.',
    'ظاهر':
        'Appearance',
    'تفکر پیش‌فرض':
        'Thinking by default',
    'جست‌وجوی وب پیش‌فرض':
        'Web search by default',
    'نمایش تدریجی پاسخ':
        'Stream replies progressively',
    'ادامهٔ خودکار پاسخ (فقط DeepSeek)':
        'Auto-continue replies (DeepSeek only)',
    'روشن (پیشنهادی)':
        'On (recommended)',
    'مفسر کد و ابزارهای Qwen خاموش می‌شوند و از مدل خواسته می‌شود همهٔ کد را کامل و در بلوک‌های کد داخل خود پاسخ بنویسد.':
        'Qwen\'s code interpreter and tools are turned off and the model is asked to write all code in full, in code blocks inside its reply.',
    'Qwen: کد کامل داخل چت (بدون ابزار)':
        'Qwen: full code inside the chat (no tools)',
    ' ثانیه':
        ' seconds',
    'مهلت درخواست':
        'Request timeout',
    'گفت‌وگو':
        'Conversation',
    'برای Qwen روش «مرورگر داخلی» پیشنهاد می‌شود: یک بار در پنجرهٔ مرورگر داخلی وارد chat.qwen.ai شوید و هر تأیید یا کپچا را خودتان انجام دهید؛ توکن همیشه تازه از همان صفحه خوانده می‌شود و توکن دستی فقط وقتی به کار می‌رود که صفحه توکنی نداشته باشد. توکن‌های وب Qwen فقط حدود ۱۵ دقیقه اعتبار دارند، پس توکن دستی زود منقضی می‌شود.\n\nاین برنامه از رابط‌های غیررسمی وب DeepSeek و Qwen استفاده می‌کند. گذرواژه را وارد نکنید؛ فقط توکن نشست وب را وارد کنید. هر توکن جداگانه در مدیر اعتبارنامهٔ ویندوز ذخیره می‌شود و هر زمان می‌توانید آن را عوض یا حذف کنید. گفت‌وگوهای قبلی با همان سرویسی ادامه می‌یابند که با آن شروع شده‌اند.':
        'For Qwen the “built-in browser” method is recommended: sign in to chat.qwen.ai once in the built-in browser window and complete any check or captcha yourself; the token is always read fresh from that page, and the manual token is only used when the page has none. Qwen web tokens are only valid for about 15 minutes, so a manual token expires quickly.\n\nThis app uses the unofficial web APIs of DeepSeek and Qwen. Do not enter your password; enter only a web session token. Each token is stored separately in Windows Credential Manager and you can change or remove it at any time. Existing conversations continue with the service they were started with.',
    'درباره':
        'About',
    'ذخیره':
        'Save',
    'انصراف':
        'Cancel',
    'توکن دستی ذخیره‌شده منقضی شده است (اعتبار توکن‌های Qwen حدود ۱۵ دقیقه است)؛ در حالت مرورگر داخلی نادیده گرفته می‌شود. بهتر است آن را حذف کنید.':
        'The saved manual token has expired (Qwen tokens last about 15 minutes); it is ignored in built-in browser mode. You should remove it.',
    'توکن ذخیره شده است؛ اتصال هنوز بررسی نشده':
        'Token saved; connection not checked yet',
    'توکنی ذخیره نشده است':
        'No token saved',
    'دستیار گفت‌وگو':
        'Chat assistant',
    'DeepSeek · Qwen — غیررسمی':
        'DeepSeek · Qwen — unofficial',
    'شروع گفت‌وگوی جدید':
        'Start a new chat',
    'جست‌وجوی گفت‌وگوها':
        'Search chats',
    'گفت‌وگوها':
        'Chats',
    'گزارش تشخیصی':
        'Diagnostic log',
    'تغییر پوسته (روشن / تیره)':
        'Toggle theme (light / dark)',
    'سرویس و مدل گفت‌وگوهای تازه':
        'Service and model for new chats',
    'پروژه':
        'Project',
    'حالت پروژه: پوشهٔ پروژه، فایل‌ها و تغییرات پیشنهادی':
        'Project mode: project folder, files and proposed changes',
    'پیام‌های قدیمی‌تر':
        'Older messages',
    'آخرین پیام‌ها':
        'Latest messages',
    'پیام خود را بنویسید…':
        'Type your message…',
    'تفکر':
        'Thinking',
    'جست‌وجوی وب':
        'Web search',
    'توقف':
        'Stop',
    'ارسال (Enter)':
        'Send (Enter)',
    'پاسخ‌ها از رابط‌های غیررسمی وب دریافت می‌شوند و ممکن است نادرست باشند.':
        'Replies come from unofficial web APIs and may be inaccurate.',
    'گفت‌وگوی {v0} · غیررسمی':
        '{v0} chat · unofficial',
    'مدل Qwen':
        'Qwen model',
    'تنظیمات بیشتر…':
        'More settings…',
    'انتخاب پوشه پروژه':
        'Choose project folder',
    'حالت پروژه برای این گفت‌وگو روشن شد. فایل‌های لازم را تیک بزنید یا با @ نام ببرید.':
        'Project mode is on for this chat. Tick the files you need or mention them with @.',
    'تغییرات را بررسی کنید؛ تا «اعمال» را نزنید چیزی نوشته نمی‌شود.':
        'Review the changes; nothing is written until you press “Apply”.',
    'تغییر پیشنهادی برای فایل {path} اعمال نشد: {error}\nلطفاً با توجه به محتوای فعلی همین فایل (پیوست شده) یک بلوک edit درست بفرست که SEARCH آن دقیقاً و فقط یک‌بار در فایل باشد، یا کل فایل را با بلوک file بفرست.':
        'The proposed change for {path} was not applied: {error}\nUsing the current content of this file (attached), please send a correct edit block whose SEARCH appears exactly once in the file, or send the whole file in a file block.',
    'متن درخواست اصلاح در کادر پیام آماده است؛ بررسی کنید و بفرستید.':
        'The fix request is ready in the message box; review it and send.',
    '{v0} فایل نوشته شد (نسخهٔ قبلی در تاریخچه ذخیره شد).':
        '{v0} files written (the previous version was saved to history).',
    '<p dir="rtl" style="color:{v0}; font-size:small;">ارسال نتایج ابزار به مدل انجام نشد؛ «تلاش دوباره» را بزنید.</p>':
        '<p dir="ltr" style="color:{v0}; font-size:small;">Sending the tool results to the model failed; press “Retry”.</p>',
    '{v0} در حال پاسخ':
        '{v0} is replying',
    'ارسال ناموفق بود':
        'Sending failed',
    'ورود یا تأیید Qwen لازم است':
        'Qwen sign-in or verification required',
    'خروجی گزارش':
        'Export log',
    'تغییر نام گفت‌وگو':
        'Rename chat',
    'عنوان:':
        'Title:',
    'خروجی گفت‌وگو':
        'Export chat',
    'مدیر اعتبارنامهٔ ویندوز در دسترس نیست':
        'Windows Credential Manager is not available',
    'ابتدا توکن Qwen را وارد کنید.':
        'Enter the Qwen token first.',
    'خروجی گفت‌وگو (Markdown / JSON)':
        'Export chat (Markdown / JSON)',
    'پاک‌کردن پیام‌ها و شروع نشست تازه':
        'Clear messages and start a new session',
    'حذف گفت‌وگو':
        'Delete chat',
    'حالت تفکر (استدلال طولانی‌تر)':
        'Thinking mode (longer reasoning)',
    'جست‌وجو در وب':
        'Search the web',
    'کپی متن انتخاب‌شده یا آخرین پیام':
        'Copy the selected text or the last message',
    'تلاش دوباره برای آخرین پیام ناموفق':
        'Retry the last failed message',
    'ادامهٔ پاسخ ناقص (برای Qwen یک پیام «ادامه بده» در همان گفت‌وگو فرستاده می‌شود)':
        'Continue a cut-off reply (for Qwen a “continue” message is sent in the same chat)',
    'سرویس: ':
        'Service: ',
    ' شروع شده است)':
        ')',
    'گفت‌وگوهای تازه با {v0} آغاز می‌شوند؛ این گفت‌وگو با {v1} ادامه می‌یابد.':
        'New chats start with {v0}; this chat continues with {v1}.',
    'بعضی فایل‌ها برای جا شدن در زمینه کوتاه شدند.':
        'Some files were truncated to fit in the context.',
    'حجم زمینهٔ پروژه زیاد است ({v0:,} نویسه)؛ ممکن است مدل آن را کامل نخواند.':
        'The project context is large ({v0:,} characters); the model may not read all of it.',
    'ابزارهای ویرایش تغییری پیشنهاد نکردند.':
        'The edit tools proposed no changes.',
    '{v0} تغییر پیشنهادی آمادهٔ بررسی است':
        '{v0} proposed changes ready for review',
    'سقف {limit} مرحلهٔ ابزار برای این درخواست رسید و عامل متوقف شد. برای ادامه، پیام تازه‌ای بفرستید.':
        'Reached the limit of {limit} tool steps for this request and the agent stopped. Send a new message to continue.',
    'عامل متوقف شد':
        'Agent stopped',
    'این درخواست ابزار دیگر فعال نیست.':
        'This tool request is no longer active.',
    'تغییرات پیشنهادی آمادهٔ بررسی است':
        'Proposed changes ready for review',
    'توکن {v0} ذخیره نشده است؛ نتایج ابزار فرستاده نشد.':
        'The {v0} token is not saved; tool results were not sent.',
    'یک ابزار در حال اجراست؛ صبر کنید یا «توقف» را بزنید.':
        'A tool is running; wait or press “Stop”.',
    'توکن {v0} ذخیره نشده است. آن را در تنظیمات وارد کنید.':
        'The {v0} token is not saved. Enter it in Settings.',
    'تلاش دوباره':
        'Retry',
    'متوقف شد':
        'Stopped',
    '\n\nپس از ورود یا تأیید، «ادامه» را بزنید؛ سپس می‌توانید پیام را با یک کلیک دوباره بفرستید (ارسال خودکار انجام نمی‌شود).':
        '\n\nAfter signing in or verifying, press “Continue”; then you can resend the message with one click (nothing is sent automatically).',
    'درخواست قبلی هنوز در حال پایان است؛ چند لحظه بعد «تلاش دوباره» را بزنید.':
        'The previous request is still finishing; press “Retry” in a moment.',
    'ذخیرهٔ گزارش':
        'Save log',
    '«تلاش دوباره» فقط برای پیام ناموفق یا قطع‌شدهٔ شما فعال است.':
        '“Retry” is only available for your failed or interrupted message.',
    'در کلیپ‌بورد کپی شد':
        'Copied to clipboard',
    'گفت‌وگو ذخیره شد':
        'Chat saved',
    'اتصال {v0} با خطای غیرمنتظره روبه‌رو شد. شاید رابط خصوصی آن تغییر کرده باشد.':
        'The {v0} connection hit an unexpected error. Its private API may have changed.',
    ' مدل دریافت شد':
        ' models fetched',
    'بررسی ناموفق بود':
        'Check failed',
    'بررسی توکن Qwen با خطای غیرمنتظره روبه‌رو شد.':
        'Checking the Qwen token hit an unexpected error.',
    'ذخیرهٔ توکن':
        'Save token',
    'ذخیرهٔ توکن در مدیر اعتبارنامهٔ ویندوز ممکن نشد.':
        'Could not save the token in Windows Credential Manager.',
    ' (این گفت‌وگو با ':
        ' (this chat started with ',
    ' ادامه می‌یابد':
        ' continues',
    'این فایل‌ها پیوست نشدند (بزرگ یا ناخوانا): ':
        'These files were not attached (too large or unreadable): ',
    'در حال دریافت تغییرات: {done} فایل کامل':
        'Receiving changes: {done} files complete',
    ' ({errors} مورد خطا دارد)':
        ' ({errors} with errors)',
    'در پنل بازبینی':
        'In the review panel',
    'خطا':
        'Error',
    'منتظر تأیید شما':
        'Waiting for your approval',
    'در حال اجرای ':
        'Running ',
    'کد کپی شد':
        'Code copied',
    'مدیر اعتبارنامهٔ ویندوز در دسترس نیست.':
        'Windows Credential Manager is not available.',
    'پیام در پایگاه داده ذخیره نشد؛ متن همچنان در کادر ارسال باقی مانده است.':
        'The message was not saved to the database; the text is still in the composer.',
    'ارسال دوباره':
        'Resend',
    'آخرین پیام شما دوباره به Qwen فرستاده شود؟':
        'Send your last message to Qwen again?',
    'هنوز گزارشی ثبت نشده است.':
        'No log has been recorded yet.',
    'این گفت‌وگوی محلی حذف شود؟':
        'Delete this local chat?',
    'پاک‌کردن گفت‌وگو':
        'Clear chat',
    'پیام‌ها پاک شوند و نشست تازه‌ای آغاز شود؟':
        'Clear the messages and start a new session?',
    'نوشتن فایل انتخاب‌شده ممکن نشد.':
        'Could not write the selected file.',
    'اتصال Qwen پذیرفته شد؛ ':
        'Qwen connection accepted; ',
    'آماده':
        'Ready',
    'در حال دریافت پاسخ':
        'Receiving reply',
    'مرورگر داخلی':
        'Built-in browser',
    'این گفت‌وگو با ':
        'This chat started with ',
    ' · در حال نوشتن {path}':
        ' · writing {path}',
    '» را اجرا کند. کارت آن را در گفت‌وگو بررسی کنید و «اجرا» یا «رد» را بزنید.':
        '”. Review its card in the chat and press “Run” or “Reject”.',
    'اجرای ابزار متوقف می‌شود…':
        'Stopping the tool…',
    'کد (تا این لحظه) کپی شد':
        'Code (so far) copied',
    'توکن':
        'Token',
    '، ':
        ', ',
    'اجرا نشد':
        'Not run',
    'مدل می‌خواهد «':
        'The model wants to run “',
    'ساخت':
        'Create',
    'ویرایش':
        'Edit',
    'حذف':
        'Delete',
    'ساخت پوشه':
        'Create folder',
    'در انتظار بررسی':
        'Pending review',
    'اعمال شد':
        'Applied',
    'رد شد':
        'Rejected',
    '<p dir="rtl" style="color:{v0};">… diff کوتاه شد</p>':
        '<p dir="ltr" style="color:{v0};">… diff truncated</p>',
    '<p dir="rtl" style="color:{v0};">این فایل حذف می‌شود ({v1} خط).</p>':
        '<p dir="ltr" style="color:{v0};">This file will be deleted ({v1} lines).</p>',
    '<p dir="rtl">تغییری در محتوا نیست.</p>':
        '<p dir="ltr">No content changes.</p>',
    'پوشه‌ای انتخاب نشده است':
        'No folder selected',
    'حالت پروژه برای این گفت‌وگو':
        'Project mode for this chat',
    'مدل می‌تواند فایل بسازد یا ویرایش کند؛ هیچ تغییری بدون تأیید شما نوشته نمی‌شود':
        'The model can create or edit files; nothing is written without your approval',
    'ابزارهای عامل (خواندن، جست‌وجو، ترمینال، وب)':
        'Agent tools (read, search, terminal, web)',
    'مدل می‌تواند ساختار پوشه را ببیند، فایل پیدا کند و بخواند و تصویرها را بررسی کند (خودکار و فقط داخل پوشهٔ پروژه).\nاجرای فرمان، دانلود و درخواست به نشانی‌های غیرمحلی فقط با زدن «اجرا» روی کارت آن انجام می‌شود.':
        'The model can see the folder structure, find and read files and inspect images (automatically, only inside the project folder).\nRunning commands, downloads and requests to non-local URLs only happen when you press “Run” on their card.',
    'اجرای خودکار فرمان‌های فقط‌خواندنی در این نشست':
        'Auto-run read-only commands in this session',
    'فقط فرمان‌هایی مثل dir، Get-Content، git status/log/diff یا node --version بدون تأیید اجرا می‌شوند؛\nهر فرمانی که چیزی را تغییر دهد همچنان تأیید می‌خواهد. با بستن برنامه خاموش می‌شود.':
        'Only commands such as dir, Get-Content, git status/log/diff or node --version run without approval;\nany command that changes something still needs approval. Turns off when the app closes.',
    'فیلتر فایل‌ها':
        'Filter files',
    'فایل‌ها را تیک بزنید یا در پیام بنویسید @نام‌فایل تا محتوایشان فرستاده شود.':
        'Tick files or write @filename in your message to send their contents.',
    'فایل‌ها':
        'Files',
    'اعمال':
        'Apply',
    'رد':
        'Reject',
    'اعمال همه':
        'Apply all',
    'درخواست اصلاح از مدل':
        'Ask the model for a fix',
    'کنار هم':
        'Side by side',
    'باز کردن در ویرایشگر':
        'Open in editor',
    'باز کردن پوشه':
        'Open folder',
    'تغییرات پیشنهادی':
        'Proposed changes',
    'بازگردانی آخرین تغییرات':
        'Undo last changes',
    'بازخوانی':
        'Refresh',
    '{n} فایل{cut} · پیوست: {att} فایل · حجم زمینه ≈ {chars:,} نویسه (~{tokens:,} توکن) از {budget:,}':
        '{n} files{cut} · attached: {att} files · context ≈ {chars:,} chars (~{tokens:,} tokens) of {budget:,}',
    'تغییرات پیشنهادی ({v0})':
        'Proposed changes ({v0})',
    'بازگردانی':
        'Undo',
    'آخرین تغییرات اعمال‌شده بازگردانده شود؟':
        'Undo the last applied changes?',
    ' — بیش از حد! چند فایل را بردارید.':
        ' — too much! Remove some files.',
    'تأیید حذف':
        'Confirm deletion',
    'پوشهٔ ذخیره‌شده پیدا نشد: ':
        'Saved folder not found: ',
    'این فایل‌ها حذف می‌شوند (نسخهٔ پشتیبان نگه داشته می‌شود):\n\n':
        'These files will be deleted (a backup is kept):\n\n',
    'اعمال نشد':
        'Not applied',
    'هیچ فایلی تغییر نکرد:\n{e}':
        'No files changed:\n{e}',
    ' — بزرگ‌تر از حد پیوست':
        ' — larger than the attachment limit',
    ' (فهرست کوتاه شد)':
        ' (list truncated)',
    'در این پنجره خودتان وارد حساب Qwen شوید و اگر تأیید یا کپچا نمایش داده شد، آن را خودتان کامل کنید. برنامه کپچا را حل نمی‌کند و کوکی‌ها را جایی منتقل نمی‌کند؛ درخواست‌ها از داخل همین صفحه ارسال می‌شوند. پس از ورود، «ادامه» را بزنید.':
        'Sign in to your Qwen account yourself in this window, and if a check or captcha appears, complete it yourself. The app does not solve captchas and does not move cookies anywhere; requests are sent from inside this page. After signing in, press “Continue”.',
    'ادامه':
        'Continue',
    'بارگذاری دوباره':
        'Reload',
    'صفحهٔ اصلی Qwen':
        'Qwen home',
    'بستن':
        'Close',
    'در انتظار ارسال':
        'Waiting to send',
    'در حال دریافت':
        'Receiving',
    'ناموفق':
        'Failed',
    'قطع‌شده':
        'Interrupted',
    '<table width="100%" height="100%" cellpadding="0"><tr><td align="center" style="padding-top:90px;"><p align="center" style="font-size:28pt; color:{v0};">✦</p><p align="center" style="font-size:x-large; font-weight:700;">چه کمکی از دستم برمی‌آید؟</p><p align="center" style="color:{v1};">گفت‌وگو با {v2} · پیام خود را در کادر پایین بنویسید</p><p align="center" style="color:{v1}; font-size:small;">Enter برای ارسال · Shift+Enter برای خط جدید</p></td></tr></table>':
        '<table width="100%" height="100%" cellpadding="0"><tr><td align="center" style="padding-top:90px;"><p align="center" style="font-size:28pt; color:{v0};">✦</p><p align="center" style="font-size:x-large; font-weight:700;">How can I help?</p><p align="center" style="color:{v1};">Chatting with {v2} · type your message in the box below</p><p align="center" style="color:{v1}; font-size:small;">Enter to send · Shift+Enter for a new line</p></td></tr></table>',
    'ساختار پوشه':
        'Folder structure',
    'یافتن فایل':
        'Find files',
    'جست‌وجو در فایل‌ها':
        'Search in files',
    'خواندن فایل':
        'Read file',
    'بررسی تصویر':
        'Inspect image',
    'درخواست HTTP':
        'HTTP request',
    'دانلود فایل':
        'Download file',
    'اجرای فرمان':
        'Run command',
    'شمارش خطوط':
        'Count lines',
    'انتقال خطوط':
        'Move lines',
    'کپی خطوط':
        'Copy lines',
    'حذف خطوط':
        'Delete lines',
    'جایگزینی خطوط':
        'Replace lines',
    'درج محتوای فایل':
        'Insert file contents',
    'جست‌وجو و جایگزینی':
        'Search and replace',
    'انتقال مسیر':
        'Move path',
    'تغییر نام':
        'Rename',
    'کپی مسیر':
        'Copy path',
    'اعمال patch':
        'Apply patch',
    '<a href="{scheme}:{index}" title="برای کپی کلیک کنید" style="text-decoration:none; color:{v0};"><span style="font-family:Consolas,Vazirmatn,\'Cascadia Mono\',monospace; background-color:{v1};">&nbsp;{v2}&nbsp;</span></a>':
        '<a href="{scheme}:{index}" title="Click to copy" style="text-decoration:none; color:{v0};"><span style="font-family:Consolas,Vazirmatn,\'Cascadia Mono\',monospace; background-color:{v1};">&nbsp;{v2}&nbsp;</span></a>',
    '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:16px;"><tr><td width="22%"></td><td><p align="right" style="color:{v0}; font-size:small; margin-bottom:4px;">شما{status_html}</p><table width="100%" cellspacing="0" cellpadding="12" bgcolor="{v1}"><tr><td dir="{dir_}" style="color:{v2};">{body_html}</td></tr></table></td></tr></table>':
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:16px;"><tr><td width="22%"></td><td><p align="left" style="color:{v0}; font-size:small; margin-bottom:4px;">You{status_html}</p><table width="100%" cellspacing="0" cellpadding="12" bgcolor="{v1}"><tr><td dir="{dir_}" style="color:{v2};">{body_html}</td></tr></table></td></tr></table>',
    'در صف':
        'Queued',
    'در حال اجرا…':
        'Running…',
    'انجام شد':
        'Done',
    '<p dir="rtl" style="color:{v0}; font-size:small; margin-top:18px; margin-bottom:6px;"><span style="color:{v1};">⚙</span>&nbsp;ابزارهای پروژه · مرحلهٔ {step}</p>':
        '<p dir="ltr" style="color:{v0}; font-size:small; margin-top:18px; margin-bottom:6px;"><span style="color:{v1};">⚙</span>&nbsp;Project tools · step {step}</p>',
    '<p dir="ltr" align="left" style="background-color:{v0}; margin-top:10px; margin-bottom:0px; margin-left:0px; margin-right:0px; color:#94a3b8; font-size:small; white-space:pre;"><span style="{MONO}">{CODE_PAD}{label}</span>&nbsp;&nbsp;&nbsp;<a href="{scheme}:{index}" style="color:#a5b4fc; text-decoration:none;">کپی کد</a></p><p dir="ltr" style="{pad} margin-top:0px; margin-bottom:0px;">&nbsp;</p>':
        '<p dir="ltr" align="left" style="background-color:{v0}; margin-top:10px; margin-bottom:0px; margin-left:0px; margin-right:0px; color:#94a3b8; font-size:small; white-space:pre;"><span style="{MONO}">{CODE_PAD}{label}</span>&nbsp;&nbsp;&nbsp;<a href="{scheme}:{index}" style="color:#a5b4fc; text-decoration:none;">Copy code</a></p><p dir="ltr" style="{pad} margin-top:0px; margin-bottom:0px;">&nbsp;</p>',
    '<a href="tool-approve:{key}" style="{link} color:{v0};">✔ اجرا</a>':
        '<a href="tool-approve:{key}" style="{link} color:{v0};">✔ Run</a>',
    '<a href="tool-reject:{key}" style="{link} color:{v0};">✖ رد</a>':
        '<a href="tool-reject:{key}" style="{link} color:{v0};">✖ Reject</a>',
    '<a href="tool-kill:{key}" style="{link} color:{v0};">■ توقف (Kill)</a>':
        '<a href="tool-kill:{key}" style="{link} color:{v0};">■ Stop (Kill)</a>',
    'بستن ▴':
        'Close ▴',
    'نمایش خروجی ▾':
        'Show output ▾',
    'پیش‌فرض سیستم':
        'System default',
    'زبان رابط کاربری؛ پس از راه‌اندازی دوباره اعمال می‌شود.':
        'Interface language; applied after a restart.',
    'زبان / Language':
        'Language / زبان',
}
