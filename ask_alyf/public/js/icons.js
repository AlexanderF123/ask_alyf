let askAlyfIconsPromise = null;

function getIconContainer() {
	let container = document.getElementById("all-symbols");
	if (container) {
		return container;
	}

	container = document.createElement("div");
	container.id = "all-symbols";
	container.style.display = "none";
	document.body.appendChild(container);
	return container;
}

function getIconSpriteUrl() {
	const version = window._version_number ? `?v=${window._version_number}` : "";
	return `/assets/ask_alyf/icons/sparkles.svg${version}`;
}

export function ensureAskAlyfIcons() {
	if (document.getElementById("icon-sparkles")) {
		return Promise.resolve();
	}

	if (askAlyfIconsPromise) {
		return askAlyfIconsPromise;
	}

	askAlyfIconsPromise = fetch(getIconSpriteUrl(), { credentials: "same-origin" })
		.then((response) => (response.ok ? response.text() : ""))
		.then((svg) => {
			if (!svg || document.getElementById("icon-sparkles")) {
				return;
			}
			getIconContainer().insertAdjacentHTML("beforeend", svg);
		})
		.catch(() => {});

	return askAlyfIconsPromise;
}

ensureAskAlyfIcons();
