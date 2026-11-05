frappe.pages["zt-document-scanner"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Document Scanner"), single_column: true });
	const root = $('<div class="zt-scan-root"></div>').appendTo(page.main);
	root.html(`<style>
		.zt-scan-root{--zt-ink:#16304a;--zt-muted:#63778b;--zt-teal:#087f8c;--zt-violet:#7357c8;color:var(--zt-ink);padding-bottom:32px}
		.zt-scan-root .zt-hero{position:relative;overflow:hidden;padding:28px 30px;margin-bottom:22px;border:0;border-radius:18px;background:linear-gradient(120deg,#123b57 0%,#087f8c 58%,#35a89e 100%);box-shadow:0 12px 30px rgba(16,67,91,.18);color:white}
		.zt-scan-root .zt-hero:after{content:"";position:absolute;width:260px;height:260px;border:1px solid rgba(255,255,255,.15);border-radius:50%;right:-70px;top:-145px;box-shadow:0 0 0 28px rgba(255,255,255,.05),0 0 0 58px rgba(255,255,255,.04)}
		.zt-scan-root .zt-hero h3{font-size:23px;font-weight:700;margin:0 0 7px;color:white}.zt-scan-root .zt-hero p{color:#d7eef0;margin-bottom:20px}
		.zt-scan-root .zt-upload-row{position:relative;z-index:1;display:flex;gap:10px;max-width:760px;align-items:center}
		.zt-scan-root .zt-mode,.zt-scan-root .zt-audio-language{height:42px;max-width:210px;border:1px solid rgba(255,255,255,.48);border-radius:9px;background:#fff;color:#30475b}
		.zt-scan-root .zt-scan-file{height:42px;padding:8px;border:1px solid rgba(255,255,255,.48);border-radius:9px;background:rgba(255,255,255,.96);color:#30475b;flex:1}
		.zt-scan-root .zt-recorder{position:relative;z-index:1;margin-top:14px}.zt-scan-root .zt-record{height:38px;padding:0 15px;border:1px solid rgba(255,255,255,.55);border-radius:9px;background:rgba(255,255,255,.14);color:#fff;font-weight:600}.zt-scan-root .zt-recording{color:#ffd9d9;margin-inline-start:10px}
		.zt-scan-root .zt-scan-upload{height:42px;padding:0 20px;border:0;border-radius:9px;background:#ffcf70;color:#42320e;font-weight:700;white-space:nowrap}.zt-scan-root .zt-scan-upload:hover{background:#ffdc94}
		.zt-scan-root .zt-panel{height:100%;padding:18px;border:1px solid #e2eaf0;border-radius:15px;background:linear-gradient(160deg,#fff 0%,#f8fbfd 100%);box-shadow:0 5px 18px rgba(29,62,88,.07)}
		.zt-scan-root .zt-panel-title{display:flex;align-items:center;gap:9px;margin:0 0 14px;font-size:15px;font-weight:700;color:var(--zt-ink)}
		.zt-scan-root .zt-step{display:inline-flex;width:27px;height:27px;align-items:center;justify-content:center;border-radius:9px;background:#e1f4f3;color:#087f8c;font-size:12px}
		.zt-scan-root .zt-viewer{display:flex;min-height:430px;align-items:center;justify-content:center;overflow:hidden;border:1px solid #dce5ea;border-radius:11px;background:linear-gradient(135deg,#eaf0f4,#f6f8fa)}
		.zt-scan-root .zt-viewer iframe{width:100%;height:430px;border:0}.zt-scan-root .zt-viewer img{max-width:100%;max-height:680px;object-fit:contain}
		.zt-scan-root .zt-extracted{min-height:430px;border:1px solid #dce5ea;border-radius:11px;background:#fffefa;color:#263d50;font-size:14px;line-height:1.75;padding:14px;resize:vertical}
		.zt-scan-root .zt-copy,.zt-scan-root .zt-copy-translation{border-radius:8px;color:#31556c;background:#eef4f8;border:1px solid #dce7ee}.zt-scan-root .zt-copy:hover,.zt-scan-root .zt-copy-translation:hover{background:#e1edf4}
		.zt-scan-root .zt-translate-panel{margin-top:20px;padding:22px;border:1px solid #e5e0f5;border-radius:15px;background:linear-gradient(115deg,#f8f6ff 0%,#f2f8ff 100%);box-shadow:0 5px 18px rgba(73,62,127,.07)}
		.zt-scan-root .zt-language{height:40px;border-radius:8px 0 0 8px;border-color:#d9d5ec}.zt-scan-root .zt-translate{height:40px;padding:0 20px;border:0;border-radius:0 8px 8px 0;background:var(--zt-violet);color:#fff;font-weight:600}.zt-scan-root .zt-translate:hover{background:#6046b1}
		.zt-scan-root .zt-translated{margin-top:14px;min-height:220px;border:1px solid #ded8f0;border-radius:10px;background:white;color:#253d52;font-size:14px;line-height:1.75;padding:14px}
		.zt-scan-root .zt-scan-error{padding-top:8px;color:#ffe4d9}.zt-scan-root .zt-record-link{margin-top:14px;color:var(--zt-muted);font-size:12px}
		@media(max-width:767px){.zt-scan-root .zt-hero{padding:22px 18px}.zt-scan-root .zt-upload-row{align-items:stretch;flex-direction:column}.zt-scan-root .zt-mode,.zt-scan-root .zt-audio-language,.zt-scan-root .zt-scan-file,.zt-scan-root .zt-scan-upload{width:100%;max-width:none}.zt-scan-root .zt-extracted{min-height:320px}.zt-scan-root .zt-panel{margin-bottom:14px}}
	</style>
	<div class="zt-hero"><h3><i class="fa fa-magic" style="margin-inline-end:8px"></i>${__("Document Scanner")}</h3>
		<p>${__("Upload an image, PDF, or audio file, or record audio here to turn it into editable text.")}</p>
		<div class="zt-upload-row"><select class="form-control zt-mode"><option value="document">${__("Image or PDF")}</option><option value="audio">${__("Audio file or recording")}</option></select>
		<select class="form-control zt-audio-language" style="display:none"><option value="">${__("Audio language (required)")}</option></select>
		<input type="file" class="form-control zt-scan-file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"><button class="btn zt-scan-upload"><i class="fa fa-cloud-upload" style="margin-inline-end:6px"></i>${__("Upload and extract")}</button></div>
		<div class="zt-recorder" style="display:none"><button class="btn zt-record"><i class="fa fa-microphone" style="margin-inline-end:6px"></i>${__("Start recording")}</button><span class="zt-recording"></span></div>
		<div class="zt-scan-error"></div></div><div class="zt-scan-result"></div>`);
	page.add_inner_button(__("Saved Scans"), () => frappe.set_route("List", "Document Scan"));
	let recordedAudio = null;
	let mediaRecorder = null;
	let mediaStream = null;
	let audioChunks = [];
	let audioLanguagesLoaded = false;
	root.find(".zt-mode").on("change", () => {
		const audioMode = root.find(".zt-mode").val() === "audio";
		root.find(".zt-audio-language,.zt-recorder").toggle(audioMode);
		root.find(".zt-scan-file").attr("accept", audioMode ? "audio/*" : ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp").val("");
		recordedAudio = null;
		root.find(".zt-recording").text("");
		if (audioMode && !audioLanguagesLoaded) {
			root.find(".zt-audio-language option:first").text(__("Loading languages…"));
			frappe.call({
				method:"zero_touch.api.scan.audio_languages",
				callback:(r) => {
					const languages = r.message || [];
					root.find(".zt-audio-language").html(`<option value="">${__("Audio language (required)")}</option>` + languages.map((lang) => `<option value="${frappe.utils.escape_html(lang.code)}">${frappe.utils.escape_html(lang.label)}</option>`).join(""));
					audioLanguagesLoaded = languages.length > 0;
					if (!audioLanguagesLoaded) root.find(".zt-scan-error").text(__("No audio languages are available."));
				},
				error:() => {
					root.find(".zt-audio-language option:first").text(__("Could not load languages. Change type and try again."));
					root.find(".zt-scan-error").text(__("Could not load audio languages. Check the server log and reload the list."));
				},
			});
		}
	});
	root.find(".zt-scan-file").on("change", () => {
		recordedAudio = null;
		root.find(".zt-recording").text("");
	});
	root.on("click", ".zt-record", async () => {
		if (!mediaRecorder || mediaRecorder.state === "inactive") {
			try {
				root.find(".zt-scan-file").val("");
				recordedAudio = null;
				mediaStream = await navigator.mediaDevices.getUserMedia({audio:true});
				const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
				mediaRecorder = new MediaRecorder(mediaStream, mime ? {mimeType:mime} : undefined);
				audioChunks = [];
				mediaRecorder.ondataavailable = (event) => { if (event.data.size) audioChunks.push(event.data); };
				mediaRecorder.onstop = () => {
					recordedAudio = new Blob(audioChunks, {type:mediaRecorder.mimeType || "audio/webm"});
					mediaStream.getTracks().forEach((track) => track.stop());
					const extension = recordedAudio.type.includes("ogg") ? "ogg" : recordedAudio.type.includes("mp4") ? "m4a" : "webm";
					recordedAudio.filename = `recording.${extension}`;
					root.find(".zt-recording").text(__("Recording ready to upload"));
					root.find(".zt-record").html(`<i class="fa fa-microphone" style="margin-inline-end:6px"></i>${__("Record again")}`);
				};
				mediaRecorder.start();
				root.find(".zt-record").html(`<i class="fa fa-stop" style="margin-inline-end:6px"></i>${__("Stop recording")}`);
				root.find(".zt-recording").text(__("Recording from your microphone…"));
			} catch (error) { frappe.msgprint(__("Microphone access is unavailable: {0}", [error.message])); }
		} else {
			mediaRecorder.stop();
			root.find(".zt-record").html(`<i class="fa fa-microphone" style="margin-inline-end:6px"></i>${__("Start recording")}`);
		}
	});
	root.on("click", ".zt-scan-upload", () => {
		const input = root.find(".zt-scan-file")[0];
		const mode = root.find(".zt-mode").val();
		const language = root.find(".zt-audio-language").val();
		const uploadFile = recordedAudio || (input.files.length ? input.files[0] : null);
		if (!uploadFile) return frappe.msgprint(__("Choose a file or record audio first."));
		if (mode === "audio" && !language) return frappe.msgprint(__("Choose the language spoken in the audio."));
		const data = new FormData(); data.append("file", uploadFile, uploadFile.filename || uploadFile.name || "audio.webm");
		data.append("mode", mode);
		if (language) data.append("language", language);
		const button = root.find(".zt-scan-upload").prop("disabled", true);
		root.find(".zt-scan-error").text("");
		fetch("/api/method/zero_touch.api.scan.upload_scan", {method:"POST", headers:{"X-Frappe-CSRF-Token":frappe.csrf_token}, body:data})
			.then(async (r) => { const j=await r.json(); if(!r.ok) throw new Error(j.exception || j._server_messages || __("Scan failed")); return j.message; })
			.then((scan) => render(scan))
			.catch((e) => root.find(".zt-scan-error").text(e.message))
			.finally(() => button.prop("disabled", false));
	});
	function render(scan) {
		const ext = (scan.filename.split(".").pop() || "").toLowerCase();
		const file = frappe.utils.escape_html(scan.file_url);
		const viewer = scan.source_type === "Audio" ? `<audio controls src="${file}" style="width:100%"></audio>` :
			ext === "pdf" ? `<iframe src="${file}#toolbar=0"></iframe>` : `<img src="${file}">`;
		root.find(".zt-scan-result").html(`<div class="row">
			<div class="col-md-6"><div class="zt-panel"><h4 class="zt-panel-title"><span class="zt-step">1</span>${frappe.utils.escape_html(scan.filename)}</h4><div class="zt-viewer">${viewer}</div></div></div>
			<div class="col-md-6"><div class="zt-panel"><h4 class="zt-panel-title"><span class="zt-step">2</span>${__("Extracted text (editable)")}</h4><textarea class="form-control zt-extracted" rows="18"></textarea>
			<button class="btn zt-copy" style="margin-top:10px"><i class="fa fa-copy" style="margin-inline-end:5px"></i>${__("Copy text")}</button></div></div></div>
			<div class="zt-translate-panel"><h4 class="zt-panel-title"><span class="zt-step" style="background:#e9e3fb;color:#7357c8">3</span>${__("Translate")}</h4>
			<div class="input-group" style="max-width:650px"><select class="form-control zt-language"><option value="">${__("Choose a language")}</option></select><span class="input-group-btn"><button class="btn zt-translate"><i class="fa fa-language" style="margin-inline-end:6px"></i>${__("Translate")}</button></span></div>
			<div class="zt-translation-result"></div></div>
			<p class="zt-record-link">${__("Saved as")}: <a href="/app/document-scan/${encodeURIComponent(scan.name)}">${frappe.utils.escape_html(scan.name)}</a></p>`);
		root.find(".zt-extracted").val(scan.text);
		root.find(".zt-copy").on("click", () => copy(root.find(".zt-extracted").val()));
		root.find(".zt-language option:first").text(__("Loading languages…"));
		frappe.call({
			method:"zero_touch.api.scan.translation_languages",
			callback:(r) => {
				const languages = r.message || [];
				root.find(".zt-language").html(`<option value="">${__("Choose a language")}</option>` + languages.map((lang) => `<option value="${frappe.utils.escape_html(lang.code)}">${frappe.utils.escape_html(lang.label)}</option>`).join(""));
				if (!languages.length) root.find(".zt-translation-result").text(__("No translation languages are available."));
			},
			error:() => {
				root.find(".zt-language option:first").text(__("Could not load languages. Reload this page."));
				root.find(".zt-translation-result").text(__("Could not load translation languages. Check the server log."));
			},
		});
		root.find(".zt-translate").on("click", () => {
			const language = root.find(".zt-language").val();
			if (!language) return frappe.msgprint(__("Enter a target language."));
			frappe.call({method:"zero_touch.api.scan.translate", args:{scan:scan.name, language, edited_text:root.find(".zt-extracted").val()}, freeze:true,
				callback:(r) => root.find(".zt-translation-result").html(`<h5 class="zt-panel-title" style="margin-top:16px">${__("Translation")}: ${frappe.utils.escape_html(r.message.language)}</h5><textarea class="form-control zt-translated" rows="10" readonly></textarea><button class="btn zt-copy-translation" style="margin-top:10px"><i class="fa fa-copy" style="margin-inline-end:5px"></i>${__("Copy translation")}</button>`).find(".zt-translated").val(r.message.text)});
		});
		root.find(".zt-translation-result").on("click", ".zt-copy-translation", () => copy(root.find(".zt-translated").val()));
	}
	function copy(text) { navigator.clipboard.writeText(text || "").then(() => frappe.show_alert({message:__("Copied"), indicator:"green"})); }
};
