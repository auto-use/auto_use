document.addEventListener('DOMContentLoaded', () => {
    // Splash screen: pick the per-OS animation at runtime so a single checkout
    // works on both macOS and Windows without any build-time file patching.
    // Each animation HTML posts 'splashDone' back to us when finished.
    const splash = document.getElementById('splashOverlay');
    if (splash) {
        const splashFrame = document.getElementById('splashFrame');
        if (splashFrame && !splashFrame.src) {
            const ua = navigator.userAgent || '';
            const plat = navigator.platform || '';
            const isMac = /Mac/i.test(plat) || /Mac OS X/i.test(ua);
            splashFrame.src = isMac ? 'mac_animation.html' : 'windows_animation.html';
        }
        window.addEventListener('message', (e) => {
            if (e.data === 'splashDone') {
                splash.style.pointerEvents = 'none';
                splash.classList.add('fade-out');
                splash.addEventListener('transitionend', () => splash.remove());
            }
        });
    }

    const llmWrapper = document.getElementById('llmWrapper');
    const currentSelection = llmWrapper.querySelector('.current-selection');
    const selectionText = currentSelection.querySelector('.selection-text');
    const dropdownOptions = document.getElementById('dropdownOptions');

    // API Key Management - existence flags only (true/null), never actual keys
    const apiKeys = {
        openrouter: null,
        groq: null,
        openai: null,
        anthropic: null,
        perplexity: null
    };


    // 1. Click to toggle the dropdown list
    llmWrapper.addEventListener('click', () => {
        if (llmWrapper.classList.contains('expanded')) {
            // Collapse: Reset height to initial (let CSS transition handle it)
            llmWrapper.style.height = '';
            llmWrapper.classList.remove('expanded');
            dropdownOptions.querySelectorAll('.active-provider').forEach(el => el.classList.remove('active-provider'));
        } else {
            // Expand: Calculate exact content height
            // First, add the expanded class to make children visible/rendered
            llmWrapper.classList.add('expanded');
            
            // Get the full height of the content including padding
            // We need to measure the scrollHeight of the wrapper or the dropdown options
            // Since wrapper grows, let's measure the children height + padding
            
            const baseHeight = 28; // Approximate base height of the button part or use dropdownOptions.scrollHeight
            const padding = 16; // Top + Bottom padding approx
            
            // Better approach: Use scrollHeight of the wrapper itself now that it's 'expanded' but constrained?
            // Or measure the dropdown-options which is the growing part.
            
            const optionsHeight = dropdownOptions.scrollHeight;
            const headerHeight = 34; // Height of the top label part
            const totalHeight = headerHeight + optionsHeight + 8; // + padding
            
            llmWrapper.style.height = `${totalHeight}px`;
        }
    });

    // 2. Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!llmWrapper.contains(e.target) && llmWrapper.classList.contains('expanded')) {
            llmWrapper.style.height = '';
            llmWrapper.classList.remove('expanded');
            dropdownOptions.querySelectorAll('.active-provider').forEach(el => el.classList.remove('active-provider'));
        }
    });

    // Store selected provider and model
    let selectedProvider = null;
    let selectedModel = null;

    // Function to complete model selection (after API key is confirmed)
    const completeModelSelection = (option, providerName, modelId) => {
        // Get the model name (text content without the icon)
        const modelName = option.cloneNode(true);
        const iconSvg = modelName.querySelector('.model-icon');
        
        // Extract just the text
        let modelText = modelName.textContent.trim();
        
        // Store the selection
        selectedProvider = providerName;
        selectedModel = modelId;
        
        // Clear current selection and add new content
        currentSelection.innerHTML = '';
        
        // Add the model name text
        const textSpan = document.createElement('span');
        textSpan.className = 'selection-text';
        textSpan.textContent = modelText;
        currentSelection.appendChild(textSpan);
        
        // If the original option had an icon, add it to the selection
        if (iconSvg) {
            const iconClone = iconSvg.cloneNode(true);
            iconClone.classList.add('selection-icon');
            currentSelection.appendChild(iconClone);
        }

        // Input stays locked — handleModelSelection controls unlock based on key status
        // (do not enable here)

        // Close the dropdown
        llmWrapper.style.height = '';
        llmWrapper.classList.remove('expanded');
        
        console.log(`Selected: ${selectedProvider} / ${selectedModel}`);
    };

    // Function to handle model selection (checks for API key first)
    const handleModelSelection = (option, providerName) => {
        const modelId = option.dataset.modelId;
        
        // Always complete model selection (update UI, store selection)
        completeModelSelection(option, providerName, modelId);
        
        // Vertex models — check vertex config instead of API key
        const isVertex = modelId && modelId.includes('vertex');
        if (isVertex) {
            fetch('/api/vertex/status')
                .then(res => res.json())
                .then(data => {
                    if (data.project_id) {
                        chatInput.disabled = false;
                        chatInput.placeholder = 'Type your task...';
                    } else {
                        chatInput.disabled = true;
                        chatInput.placeholder = 'Configure GCP Vertex in Settings first...';
                        if (settingsOverlay) {
                            loadKeyStatus();
                            showSettingsView('apikeys');
                            settingsOverlay.classList.add('active');
                        }
                    }
                })
                .catch(err => console.error('Failed to check vertex status:', err));
            return;
        }
        
        // Then check if key exists
        fetch('/api/keys/status')
            .then(res => res.json())
            .then(status => {
                if (status[providerName]) {
                    // Key exists — unlock input
                    chatInput.disabled = false;
                    chatInput.placeholder = 'Type your task...';
                } else {
                    // No key — keep input locked, open settings
                    chatInput.disabled = true;
                    chatInput.placeholder = 'Add API key in Settings first...';
                    if (settingsOverlay) {
                        loadKeyStatus();
                        showSettingsView('apikeys');
                        settingsOverlay.classList.add('active');
                    }
                }
            })
            .catch(err => {
                console.error('Failed to check key status:', err);
            });
    };

    // Function to render providers and models
    const renderProviders = (providers) => {
        dropdownOptions.innerHTML = '';

        if (!providers || providers.length === 0) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'provider-item';
            errorDiv.innerHTML = '<span>No providers found</span>';
            dropdownOptions.appendChild(errorDiv);
            return;
        }

        providers.forEach(provider => {
            const providerItem = document.createElement('div');
            providerItem.className = 'provider-item';

            const providerNameSpan = document.createElement('span');
            providerNameSpan.textContent = provider.name;
            providerItem.appendChild(providerNameSpan);

            // Show sub-menu on hover, keep last hovered one visible
            providerItem.addEventListener('mouseenter', () => {
                dropdownOptions.querySelectorAll('.provider-item.active-provider').forEach(el => {
                    el.classList.remove('active-provider');
                });
                providerItem.classList.add('active-provider');
            });

            const subMenu = document.createElement('div');
            subMenu.className = 'sub-menu';

            const subMenuCard = document.createElement('div');
            subMenuCard.className = 'sub-menu-card';

            // Add glass effects
            subMenuCard.innerHTML = `
                <div class="liquidGlass-effect-btn"></div>
                <div class="liquidGlass-tint-btn"></div>
                <div class="liquidGlass-shine-btn"></div>
            `;

            const subMenuContent = document.createElement('div');
            subMenuContent.className = 'sub-menu-content';

            provider.models.forEach(model => {
                const modelOption = document.createElement('div');
                modelOption.className = 'model-option';
                modelOption.dataset.modelId = model.id; // Store ID for backend use

                const modelNameText = document.createTextNode(model.display_name);
                modelOption.appendChild(modelNameText);

                if (model.reasoning_support) {
                    const svgIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                    svgIcon.classList.add('model-icon');
                    const useElement = document.createElementNS("http://www.w3.org/2000/svg", "use");
                    useElement.setAttribute('href', '#icon-brain');
                    svgIcon.appendChild(useElement);
                    modelOption.appendChild(svgIcon);
                }

                // Add click listener
                modelOption.addEventListener('click', (e) => {
                    e.stopPropagation(); // Prevent wrapper toggle
                    handleModelSelection(modelOption, provider.id);
                });

                subMenuContent.appendChild(modelOption);
            });

            subMenuCard.appendChild(subMenuContent);
            subMenu.appendChild(subMenuCard);
            providerItem.appendChild(subMenu);
            dropdownOptions.appendChild(providerItem);
        });
    };

    // Initialize fetching data
    const loadData = () => {
        fetch('/api/providers')
            .then(response => response.json())
            .then(providers => {
                renderProviders(providers);
            })
            .catch(err => {
                console.error("Failed to load providers:", err);
                renderProviders([]);
            });
    };

    // Position settings button dynamically next to LLM button
    const settingsBtnEl = document.getElementById('settingsBtn');
    const positionSettingsBtn = () => {
        if (!settingsBtnEl || !llmWrapper) return;
        const rect = llmWrapper.getBoundingClientRect();
        settingsBtnEl.style.left = (rect.right + 10) + 'px';
    };
    
    // Reposition on load, resize, and after any selection change
    positionSettingsBtn();
    window.addEventListener('resize', positionSettingsBtn);
    
    // Observe LLM button size/position changes (e.g. after model selection or layout switch)
    const resizeObserver = new ResizeObserver(positionSettingsBtn);
    resizeObserver.observe(llmWrapper);
    llmWrapper.addEventListener('transitionend', positionSettingsBtn);

    // Load immediately
    loadData();

    // Load API key status on startup
    fetch('/api/keys/status')
        .then(res => res.json())
        .then(status => {
            Object.keys(status).forEach(provider => {
                apiKeys[provider] = status[provider] ? true : null;
            });
        })
        .catch(err => console.error('Failed to load key status:', err));

    // ============================================
    // SETTINGS PANEL - Open / Close
    // ============================================
    const settingsBtn = document.getElementById('settingsBtn');
    const settingsOverlay = document.getElementById('settingsOverlay');
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    const settingsMenuView = document.getElementById('settingsMenuView');
    const settingsApikeysView = document.getElementById('settingsApikeysView');
    const settingsRemoteView = document.getElementById('settingsRemoteView');

    // Helper: seal a provider row (key exists)
    const sealProviderRow = (row) => {
        const input = row.querySelector('.settings-provider-input');
        const deleteBtn = row.querySelector('.settings-delete-btn');
        input.value = '';
        input.placeholder = 'API Key already exists';
        input.disabled = true;
        deleteBtn.style.display = 'flex';
    };

    // Helper: unseal a provider row (no key)
    const unsealProviderRow = (row) => {
        const input = row.querySelector('.settings-provider-input');
        const deleteBtn = row.querySelector('.settings-delete-btn');
        const provider = row.dataset.provider;
        const placeholders = { openrouter: 'sk-or-...', groq: 'gsk_...', openai: 'sk-...', anthropic: 'sk-ant-...', google: 'AIza...' };
        input.value = '';
        input.placeholder = placeholders[provider] || 'Enter API key...';
        input.disabled = false;
        deleteBtn.style.display = 'none';
    };

    // Load key status from backend
    const loadKeyStatus = () => {
        fetch('/api/keys/status')
            .then(res => res.json())
            .then(status => {
                document.querySelectorAll('.settings-provider-row').forEach(row => {
                    const provider = row.dataset.provider;
                    if (status[provider]) {
                        sealProviderRow(row);
                    } else {
                        unsealProviderRow(row);
                    }
                });
                // If Google has no API key, check if Vertex is configured instead
                if (!status['google']) {
                    fetch('/api/vertex/status')
                        .then(res => res.json())
                        .then(data => {
                            if (data.project_id) {
                                const googleRow = document.querySelector('.settings-provider-row[data-provider="google"]');
                                if (googleRow) {
                                    sealProviderRow(googleRow);
                                    const input = googleRow.querySelector('.settings-provider-input');
                                    if (input) input.placeholder = 'Vertex AI configured';
                                }
                            }
                        })
                        .catch(() => {});
                }
            })
            .catch(err => console.error('Failed to load key status:', err));
    };

    // Delete button handlers
    document.querySelectorAll('.settings-delete-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('.settings-provider-row');
            const provider = row.dataset.provider;

            fetch('/api/keys/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider })
            })
            .then(res => res.json())
            .then(() => {
                unsealProviderRow(row);
                // Clear in-memory flag
                apiKeys[provider] = null;
                // Lock input and reset if deleted key belongs to the active provider
                if (provider === selectedProvider) {
                    chatInput.disabled = true;
                    chatInput.value = '';
                    chatInput.placeholder = 'Select a model to start...';
                    selectedProvider = null;
                    selectedModel = null;
                    // Reset LLM button to default
                    currentSelection.innerHTML = '';
                    const defaultSpan = document.createElement('span');
                    defaultSpan.className = 'selection-text';
                    defaultSpan.textContent = 'LLM Provider';
                    currentSelection.appendChild(defaultSpan);
                }
            })
            .catch(err => console.error('Failed to delete key:', err));
        });
    });

    // ============================================
    // GCP VERTEX AI POPUP
    // ============================================
    const gcpVertexBtn = document.getElementById('gcpVertexBtn');
    const vertexOverlay = document.getElementById('vertexOverlay');
    const vertexDoneBtn = document.getElementById('vertexDoneBtn');
    const vertexProjectId = document.getElementById('vertexProjectId');
    const vertexLocation = document.getElementById('vertexLocation');

    // Location field — muted by default, vivid on edit
    if (vertexLocation) {
        vertexLocation.addEventListener('focus', () => {
            if (vertexLocation.value === 'global') {
                vertexLocation.select();
            }
            vertexLocation.classList.add('edited');
        });
        vertexLocation.addEventListener('blur', () => {
            if (!vertexLocation.value.trim()) {
                vertexLocation.value = 'global';
            }
            if (vertexLocation.value === 'global') {
                vertexLocation.classList.remove('edited');
            }
        });
    }

    // Open vertex popup
    if (gcpVertexBtn && vertexOverlay) {
        gcpVertexBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Load existing vertex config
            fetch('/api/vertex/status')
                .then(res => res.json())
                .then(data => {
                    if (data.project_id) vertexProjectId.value = data.project_id;
                    const loc = data.location || 'global';
                    vertexLocation.value = loc;
                    if (loc !== 'global') vertexLocation.classList.add('edited');
                    else vertexLocation.classList.remove('edited');
                })
                .catch(() => {});
            vertexOverlay.classList.add('active');
        });

        // Close on overlay click
        vertexOverlay.addEventListener('click', (e) => {
            if (e.target === vertexOverlay) {
                vertexOverlay.classList.remove('active');
            }
        });
    }

    // Save vertex config
    if (vertexDoneBtn) {
        vertexDoneBtn.addEventListener('click', () => {
            const projectId = vertexProjectId.value.trim();
            if (!projectId) {
                vertexProjectId.style.animation = 'shake 0.4s ease';
                setTimeout(() => vertexProjectId.style.animation = '', 400);
                return;
            }
            const location = vertexLocation.value.trim() || 'global';
            fetch('/api/vertex/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId, location: location })
            })
            .then(res => res.json())
            .then(() => {
                gcpVertexBtn.classList.add('configured');
                vertexOverlay.classList.remove('active');
                // Unlock chat input if a Vertex model is currently selected
                if (selectedModel && selectedModel.includes('vertex')) {
                    chatInput.disabled = false;
                    chatInput.placeholder = 'Type your task...';
                }
            })
            .catch(err => console.error('Failed to save vertex config:', err));
        });
    }

    // Load vertex status on startup to tint button
    fetch('/api/vertex/status')
        .then(res => res.json())
        .then(data => {
            if (data.project_id && gcpVertexBtn) {
                gcpVertexBtn.classList.add('configured');
            }
        })
        .catch(() => {});

    // Helper: switch settings view
    const showSettingsView = (viewName) => {
        settingsMenuView.classList.remove('active');
        settingsApikeysView.classList.remove('active');
        settingsRemoteView.classList.remove('active');
        if (viewName === 'apikeys') settingsApikeysView.classList.add('active');
        else if (viewName === 'remote') settingsRemoteView.classList.add('active');
        else settingsMenuView.classList.add('active');
    };

    // Helper: reset to menu view when closing
    const resetSettingsToMenu = () => {
        settingsOverlay.classList.remove('active');
        // Reset to menu after transition completes
        setTimeout(() => showSettingsView('menu'), 300);
    };

    if (settingsBtn && settingsOverlay) {
        settingsBtn.addEventListener('click', () => {
            loadKeyStatus();
            showSettingsView('menu');
            settingsOverlay.classList.add('active');
        });

        // Close button on menu view
        document.getElementById('settingsCloseBtn').addEventListener('click', () => {
            resetSettingsToMenu();
        });

        // Menu item navigation
        document.querySelectorAll('.settings-menu-item').forEach(item => {
            item.addEventListener('click', () => {
                const view = item.dataset.view;
                if (view === 'apikeys') {
                    loadKeyStatus();
                    showSettingsView('apikeys');
                } else if (view === 'remote') {
                    showSettingsView('remote');
                    loadRemoteStatus();
                }
            });
        });

        // Back buttons
        document.querySelectorAll('.settings-back-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                showSettingsView('menu');
            });
        });

        // Save button (API Keys)
        settingsSaveBtn.addEventListener('click', () => {
            const savePromises = [];
            document.querySelectorAll('.settings-provider-row').forEach(row => {
                const input = row.querySelector('.settings-provider-input');
                const provider = row.dataset.provider;
                const value = input.value.trim();

                if (!input.disabled && value) {
                    savePromises.push(
                        fetch('/api/keys/save', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider, key: value })
                        })
                        .then(res => res.json())
                        .then(() => {
                            sealProviderRow(row);
                            apiKeys[provider] = true;
                        })
                    );
                }
            });

            Promise.all(savePromises)
                .then(() => {
                    resetSettingsToMenu();
                    if (selectedProvider && selectedModel) {
                        const isVertex = selectedModel.includes('vertex');
                        if (isVertex) {
                            fetch('/api/vertex/status')
                                .then(res => res.json())
                                .then(data => {
                                    if (data.project_id) {
                                        chatInput.disabled = false;
                                        chatInput.placeholder = 'Type your task...';
                                    } else {
                                        chatInput.disabled = true;
                                        chatInput.placeholder = 'Configure GCP Vertex in Settings first...';
                                    }
                                })
                                .catch(() => {});
                        } else if (apiKeys[selectedProvider]) {
                            chatInput.disabled = false;
                            chatInput.placeholder = 'Type your task...';
                        }
                    }
                })
                .catch(err => {
                    console.error('Failed to save keys:', err);
                    resetSettingsToMenu();
                });
        });

        // Remote Connection — QR + status logic
        const remoteSetup = document.getElementById('remoteSetup');
        const remoteConnected = document.getElementById('remoteConnected');
        const remoteQrContainer = document.getElementById('remoteQrContainer');
        const remoteBotName = document.getElementById('remoteBotName');
        const remoteDisconnectBtn = document.getElementById('remoteDisconnectBtn');

        function loadRemoteStatus() {
            fetch('/api/telegram/status')
                .then(res => res.json())
                .then(data => {
                    if (data.connected && data.bot_username) {
                        remoteSetup.style.display = 'none';
                        remoteConnected.style.display = 'flex';
                        remoteBotName.textContent = '@' + data.bot_username;
                    } else {
                        remoteSetup.style.display = 'flex';
                        remoteConnected.style.display = 'none';
                        const pairUrl = 'http://' + data.local_ip + ':5000/pair';
                        remoteQrContainer.innerHTML = '';
                        new QRCode(remoteQrContainer, {
                            text: pairUrl,
                            width: 160,
                            height: 160,
                            colorDark: '#ffffff',
                            colorLight: 'transparent',
                            correctLevel: QRCode.CorrectLevel.M
                        });
                    }
                })
                .catch(() => {});
        }

        if (remoteDisconnectBtn) {
            remoteDisconnectBtn.addEventListener('click', () => {
                fetch('/api/telegram/disconnect', { method: 'POST' })
                    .then(() => loadRemoteStatus())
                    .catch(() => {});
            });
        }

        settingsOverlay.addEventListener('click', (e) => {
            if (e.target === settingsOverlay) {
                resetSettingsToMenu();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && settingsOverlay.classList.contains('active')) {
                resetSettingsToMenu();
            }
        });
    }

    // Function to update the image stream (called from Python)
    window.updateAgentImage = (base64Image) => {
        const imgElement = document.querySelector('.stream-image');
        if (imgElement && base64Image) {
            imgElement.src = `data:image/jpeg;base64,${base64Image}`;
            imgElement.style.display = 'block'; // Show image when data arrives
        }
    };
    
    // Milestone streaming - word by word, stacking vertically
    window.streamMilestone = (text) => {
        const milestoneStream = document.getElementById('milestoneStream');
        if (!milestoneStream) return;
        
        // Create new milestone line
        const milestoneLine = document.createElement('div');
        milestoneLine.className = 'milestone-line';
        milestoneStream.appendChild(milestoneLine);
        
        // Split text into words
        const words = text.split(/\s+/).filter(w => w.length > 0);
        let currentIndex = 0;
        
        // Fast streaming speed (milliseconds per word)
        const speed = 30;
        
        const streamWord = () => {
            if (currentIndex < words.length) {
                // Add word with space
                if (currentIndex > 0) {
                    milestoneLine.textContent += ' ';
                }
                milestoneLine.textContent += words[currentIndex];
                currentIndex++;
                
                // Auto-scroll to bottom
                milestoneStream.parentElement.scrollTop = milestoneStream.parentElement.scrollHeight;
                
                setTimeout(streamWord, speed);
            }
        };
        
        // Start streaming
        streamWord();
    };

    // Word-by-word streaming for agent text in the response strip
    let streamingTimeout = null;
    window.streamAgentText = (text) => {
        const agentText = document.getElementById('agentText');
        const agentStrip = document.getElementById('agentResponseStrip');
        
        if (!agentText || !agentStrip) return;
        
        // Make sure strip is visible
        agentStrip.classList.add('active');
        
        // Clear any existing streaming
        if (streamingTimeout) {
            clearTimeout(streamingTimeout);
        }
        
        // Split text into words
        const words = text.split(/\s+/).filter(w => w.length > 0);
        let currentIndex = 0;
        let currentLine = '';
        
        // Speed in milliseconds per word (fast but readable)
        const baseSpeed = 25;
        
        const streamWord = () => {
            if (currentIndex < words.length) {
                // Add next word to current line
                const testLine = currentLine ? currentLine + ' ' + words[currentIndex] : words[currentIndex];
                
                // Temporarily set to measure width
                agentText.textContent = testLine;
                
                // Check if text overflows the container
                if (agentText.scrollWidth > agentText.clientWidth) {
                    // Reset - start fresh from left with current word
                    currentLine = words[currentIndex];
                    agentText.textContent = currentLine;
                } else {
                    // Fits - keep adding
                    currentLine = testLine;
                }
                
                currentIndex++;
                streamingTimeout = setTimeout(streamWord, baseSpeed);
            }
        };
        
        // Start streaming
        streamWord();
    };


    // 4. Auto-resize Chat Input
    const chatInput = document.querySelector('.chat-input');
    
    if (chatInput) {
        // Function to adjust height
        const adjustHeight = () => {
            // Reset height to auto to get the correct scrollHeight
            chatInput.style.height = 'auto';
            
            // Calculate new height (clamped by CSS max-height)
            const newHeight = Math.min(chatInput.scrollHeight, 150); // 150px matches CSS max-height
            
            // Apply new height, respecting minimum
            chatInput.style.height = `${Math.max(newHeight, 44)}px`; // 44px matches CSS min-height base
        };

        // Event listeners for auto-resize
        chatInput.addEventListener('input', adjustHeight);
        
        // Initial adjustment
        adjustHeight();

        // 5. Handle Enter key to start agent
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault(); // Prevent default newline
                
                const message = chatInput.value.trim();
                if (message && selectedProvider && selectedModel) {
                    // Show Agent Response Strip
                    const agentStrip = document.getElementById('agentResponseStrip');
                    const agentText = document.getElementById('agentText');
                    // Get the stop button
                    const stopBtn = document.getElementById('stopAgentBtn');
                    
                    if (agentStrip) {
                        agentStrip.classList.add('active');
                        // Disable input
                        chatInput.disabled = true;
                        chatInput.classList.add('agent-active');
                        agentText.textContent = 'Starting agent...';

                        // Show Stop Button
                        if (stopBtn) stopBtn.classList.add('active');

                        // Switch to split layout
                        document.getElementById('imageStreamContainer').classList.add('agent-visible');
                        document.getElementById('chatWrapper').classList.add('split-layout');
                        document.getElementById('llmWrapper').classList.add('split-layout');

                        // Hide eyes only, keep glow
                        const welcomeEl = document.getElementById('welcomeOverlay');
                        if (welcomeEl) welcomeEl.classList.add('eyes-hidden');

                        // Clear milestone stream for fresh start
                        const milestoneStream = document.getElementById('milestoneStream');
                        if (milestoneStream) {
                            milestoneStream.innerHTML = '';
                        }
                    }
                    
                    // Send request to start agent
                    fetch('/api/start-agent', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            provider: selectedProvider,
                            model: selectedModel,
                            task: message
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'started') {
                            agentText.textContent = 'Agent running...';
                            // Clear input after successful start
                            chatInput.value = '';
                            adjustHeight();
                        } else if (data.error) {
                            agentText.textContent = `Error: ${data.error}`;
                            // Re-enable input on error
                            chatInput.disabled = false;
                            if (stopBtn) stopBtn.classList.remove('active');
                        }
                    })
                    .catch(err => {
                        console.error('Failed to start agent:', err);
                        agentText.textContent = 'Failed to start agent';
                        // Re-enable input on error
                        chatInput.disabled = false;
                        if (stopBtn) stopBtn.classList.remove('active');
                    });
                }
            }
        });
        
        // 6. Handle Stop Button Click
        const stopBtn = document.getElementById('stopAgentBtn');
        if (stopBtn) {
            stopBtn.addEventListener('click', () => {
                // Stop streaming immediately
                if (streamingTimeout) {
                    clearTimeout(streamingTimeout);
                    streamingTimeout = null;
                }

                const agentText = document.getElementById('agentText');
                if (agentText) agentText.textContent = 'Stopping agent...';

                // Pop-vanish the button
                stopBtn.classList.add('pop-vanish');
                setTimeout(() => {
                    stopBtn.classList.remove('active', 'pop-vanish');
                }, 600);

                // Force-close any active tool animations immediately
                if (window.webSearchEnd) window.webSearchEnd();
                if (window.shellEnd) window.shellEnd();

                fetch('/api/stop-agent', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        console.log('Agent stop requested:', data);
                        const agentStrip = document.getElementById('agentResponseStrip');
                        if (agentStrip) agentStrip.classList.remove('active');

                        // Revert to centered layout
                        document.getElementById('imageStreamContainer').classList.remove('agent-visible');
                        document.getElementById('chatWrapper').classList.remove('split-layout');
                        document.getElementById('llmWrapper').classList.remove('split-layout');

                        chatInput.disabled = false;
                        chatInput.classList.remove('agent-active');
                        chatInput.focus();
                    })
                    .catch(err => console.error('Error stopping agent:', err));
            });
        }
    }
    
    // Agent completion handler (called from Python when agent finishes naturally)
    window.agentComplete = () => {
        const stopBtn = document.getElementById('stopAgentBtn');
        const agentStrip = document.getElementById('agentResponseStrip');
        const chatInput = document.querySelector('.chat-input');
        
        // Clear any streaming
        if (streamingTimeout) {
            clearTimeout(streamingTimeout);
            streamingTimeout = null;
        }
        
        // Hide Stop Button (skip if already gone from click)
        if (stopBtn && stopBtn.classList.contains('active') && !stopBtn.classList.contains('pop-vanish')) {
            stopBtn.classList.add('pop-vanish');
            setTimeout(() => {
                stopBtn.classList.remove('active', 'pop-vanish');
            }, 600);
        }
        
        // Force-close any active tool animations immediately
        if (window.webSearchEnd) window.webSearchEnd();
        if (window.shellEnd) window.shellEnd();

        // Hide Strip
        if (agentStrip) agentStrip.classList.remove('active');

        // Revert to centered layout
        document.getElementById('imageStreamContainer').classList.remove('agent-visible');
        document.getElementById('chatWrapper').classList.remove('split-layout');
        document.getElementById('llmWrapper').classList.remove('split-layout');

        // Enable Input
        if (chatInput) {
            chatInput.disabled = false;
            chatInput.classList.remove('agent-active');
            chatInput.focus();
        }
    };

    // ============================================
    // GLOBE ANIMATION FOR WEB SEARCH
    // ============================================
    
    const mainGlobeContainer = document.getElementById('mainGlobeContainer');
    const imageStreamContainer = document.getElementById('imageStreamContainer');
    
    let globeInitialized = false;
    let globeScene, globeCamera, globeRenderer, globeEarth, globeNetworkGroup;
    let globeParticles, globeLineMesh, globeActivePackets;
    let globeAnimationId = null;
    
    const initMainGlobe = () => {
        if (globeInitialized || !mainGlobeContainer) return;
        globeInitialized = true;
        
        // Get container dimensions for responsive sizing
        const containerRect = mainGlobeContainer.getBoundingClientRect();
        const size = Math.min(containerRect.width, containerRect.height) * 0.9;
        
        // Scene setup - transparent background
        globeScene = new THREE.Scene();
        
        globeCamera = new THREE.PerspectiveCamera(45, 1, 1, 1000);
        globeCamera.position.z = 12;
        
        globeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        globeRenderer.setClearColor(0x000000, 0);
        globeRenderer.setSize(size, size);
        globeRenderer.setPixelRatio(window.devicePixelRatio);
        mainGlobeContainer.appendChild(globeRenderer.domElement);
        
        // Texture generation helpers
        const getX = (lon) => (lon + 180) * (4096 / 360);
        const getY = (lat) => ((-lat) + 90) * (2048 / 180);
        
        const drawContinentsPath = (ctx) => {
            ctx.beginPath();
            const drawPoly = (coords) => {
                ctx.moveTo(getX(coords[0][0]), getY(coords[0][1]));
                for (let i = 1; i < coords.length; i++) {
                    ctx.lineTo(getX(coords[i][0]), getY(coords[i][1]));
                }
            };
            drawPoly([[-77, 8], [-75, 11], [-60, 10], [-50, 5], [-35, -5], [-35, -10], [-39, -20], [-40, -30], [-55, -55], [-70, -55], [-75, -50], [-73, -40], [-71, -30], [-75, -20], [-81, -5], [-77, 8]]);
            drawPoly([[-165, 65], [-120, 70], [-90, 75], [-70, 70], [-60, 60], [-55, 52], [-75, 35], [-80, 25], [-82, 9], [-95, 18], [-105, 20], [-125, 35], [-125, 45], [-130, 50], [-165, 65]]);
            drawPoly([[-50, 60], [-40, 65], [-30, 80], [-60, 80], [-50, 60]]);
            drawPoly([[-15, 35], [10, 37], [30, 31], [40, 15], [51, 11], [45, -10], [40, -15], [35, -30], [20, -35], [10, -5], [5, 5], [-10, 5], [-17, 15], [-15, 35]]);
            drawPoly([[43, -25], [50, -15], [49, -12], [44, -22]]);
            drawPoly([[-10, 36], [-9, 43], [0, 50], [10, 55], [25, 70], [40, 65], [35, 45], [25, 35], [15, 40], [10, 45], [5, 42], [-10, 36]]);
            drawPoly([[-5, 50], [2, 51], [0, 58], [-6, 56]]);
            drawPoly([[40, 65], [60, 75], [100, 75], [170, 70], [140, 50], [130, 40], [120, 30], [120, 20], [110, 10], [100, 15], [90, 22], [80, 5], [70, 10], [60, 25], [50, 30], [40, 45], [40, 65]]);
            drawPoly([[130, 32], [138, 36], [142, 40], [140, 45], [135, 35]]);
            drawPoly([[100, 0], [110, -5], [140, -5], [150, -10], [130, 0]]);
            drawPoly([[113, -25], [130, -12], [145, -10], [153, -25], [150, -38], [135, -35], [115, -35], [113, -25]]);
            drawPoly([[166, -45], [174, -35], [178, -38], [168, -47]]);
            ctx.closePath();
        };
        
        // Color texture
        const createColorTexture = () => {
            const canvas = document.createElement('canvas');
            canvas.width = 4096; canvas.height = 2048;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, 4096, 2048);
            ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
            ctx.shadowBlur = 30;
            ctx.fillStyle = '#dcdcdc';
            ctx.strokeStyle = '#555555';
            ctx.lineWidth = 4;
            ctx.lineJoin = 'round';
            drawContinentsPath(ctx);
            ctx.fill();
            ctx.stroke();
            ctx.globalCompositeOperation = 'source-atop';
            for (let i = 0; i < 2000; i++) {
                const x = Math.random() * 4096;
                const y = Math.random() * 2048;
                const r = 5 + Math.random() * 20;
                ctx.fillStyle = 'rgba(200, 200, 200, 0.1)';
                ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI*2); ctx.fill();
            }
            ctx.shadowColor = 'transparent';
            ctx.strokeStyle = '#cccccc';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for(let x = 0; x < 4096; x += 60) { ctx.moveTo(x, 0); ctx.lineTo(x, 2048); }
            for(let y = 0; y < 2048; y += 60) { ctx.moveTo(0, y); ctx.lineTo(4096, y); }
            ctx.stroke();
            return new THREE.CanvasTexture(canvas);
        };
        
        // Height texture
        const createHeightTexture = () => {
            const canvas = document.createElement('canvas');
            canvas.width = 4096; canvas.height = 2048;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, 4096, 2048);
            ctx.save();
            drawContinentsPath(ctx);
            ctx.clip();
            ctx.fillStyle = '#808080';
            ctx.fillRect(0, 0, 4096, 2048);
            for (let i = 0; i < 10000; i++) {
                const x = Math.random() * 4096;
                const y = Math.random() * 2048;
                const radius = 5 + Math.random() * 30;
                const shade = Math.floor(100 + Math.random() * 155);
                const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
                grad.addColorStop(0, `rgba(${shade}, ${shade}, ${shade}, 0.5)`);
                grad.addColorStop(1, `rgba(${shade}, ${shade}, ${shade}, 0)`);
                ctx.fillStyle = grad;
                ctx.beginPath();
                ctx.arc(x, y, radius, 0, Math.PI*2);
                ctx.fill();
            }
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 2;
            drawContinentsPath(ctx);
            ctx.stroke();
            ctx.restore();
            return new THREE.CanvasTexture(canvas);
        };
        
        // Earth
        const earthGeo = new THREE.SphereGeometry(4, 128, 128);
        const earthMat = new THREE.MeshPhongMaterial({
            map: createColorTexture(),
            displacementMap: createHeightTexture(),
            displacementScale: 0.5,
            displacementBias: 0,
            color: 0xffffff,
            specular: 0x333333,
            shininess: 8
        });
        globeEarth = new THREE.Mesh(earthGeo, earthMat);
        globeScene.add(globeEarth);
        
        // Atmosphere
        const atmGeo = new THREE.SphereGeometry(4.2, 64, 64);
        const atmMat = new THREE.MeshBasicMaterial({
            color: 0x888888,
            transparent: true,
            opacity: 0.05,
            side: THREE.BackSide
        });
        const atmosphere = new THREE.Mesh(atmGeo, atmMat);
        globeScene.add(atmosphere);
        
        // Network
        const particlesCount = 100;
        const connectionDistance = 2.5;
        const sphereRadius = 4.4;
        
        globeNetworkGroup = new THREE.Group();
        globeScene.add(globeNetworkGroup);
        
        const packetColors = [0x222222, 0x333333, 0x111111];
        const particleGeo = new THREE.SphereGeometry(0.04, 8, 8);
        globeParticles = [];
        
        for (let i = 0; i < particlesCount; i++) {
            const phi = Math.acos(-1 + (2 * i) / particlesCount);
            const theta = Math.sqrt(particlesCount * Math.PI) * phi;
            const greyVal = 0.5 + Math.random() * 0.3;
            const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(greyVal, greyVal, greyVal) });
            const mesh = new THREE.Mesh(particleGeo, mat);
            mesh.position.setFromSphericalCoords(sphereRadius, phi, theta);
            mesh.position.x += (Math.random() - 0.5) * 0.2;
            mesh.position.y += (Math.random() - 0.5) * 0.2;
            mesh.position.z += (Math.random() - 0.5) * 0.2;
            mesh.userData = {
                velocity: new THREE.Vector3((Math.random() - 0.5) * 0.005, (Math.random() - 0.5) * 0.005, (Math.random() - 0.5) * 0.005),
                packetColor: packetColors[Math.floor(Math.random() * packetColors.length)]
            };
            globeNetworkGroup.add(mesh);
            globeParticles.push(mesh);
        }
        
        const lineMaterial = new THREE.LineBasicMaterial({ color: 0x999999, transparent: true, opacity: 0.2 });
        globeLineMesh = new THREE.LineSegments(new THREE.BufferGeometry(), lineMaterial);
        globeNetworkGroup.add(globeLineMesh);
        
        // Packets
        const packetGeo = new THREE.BufferGeometry();
        const packetMat = new THREE.PointsMaterial({
            size: 0.16,
            vertexColors: true,
            transparent: true,
            opacity: 0.9,
            map: (() => {
                const canvas = document.createElement('canvas');
                canvas.width = 32; canvas.height = 32;
                const ctx = canvas.getContext('2d');
                ctx.beginPath();
                ctx.arc(16, 16, 14, 0, Math.PI * 2);
                ctx.fillStyle = 'white';
                ctx.fill();
                return new THREE.CanvasTexture(canvas);
            })()
        });
        const packetSystem = new THREE.Points(packetGeo, packetMat);
        globeNetworkGroup.add(packetSystem);
        globeActivePackets = [];
        
        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
        globeScene.add(ambientLight);
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(20, 10, 20);
        globeScene.add(dirLight);
        const rimLight = new THREE.DirectionalLight(0xeeeeee, 0.3);
        rimLight.position.set(-10, 10, -20);
        globeScene.add(rimLight);
        
        // Animation loop
        const animateGlobe = () => {
            globeAnimationId = requestAnimationFrame(animateGlobe);
            
            globeEarth.rotation.y += 0.003;
            globeNetworkGroup.rotation.y += 0.0032;
            
            const linePositions = [];
            const connections = [];
            
            globeParticles.forEach((p) => {
                p.position.add(p.userData.velocity);
                p.position.normalize().multiplyScalar(sphereRadius);
            });
            
            for (let i = 0; i < globeParticles.length; i++) {
                for (let j = i + 1; j < globeParticles.length; j++) {
                    const dist = globeParticles[i].position.distanceTo(globeParticles[j].position);
                    if (dist < connectionDistance) {
                        linePositions.push(
                            globeParticles[i].position.x, globeParticles[i].position.y, globeParticles[i].position.z,
                            globeParticles[j].position.x, globeParticles[j].position.y, globeParticles[j].position.z
                        );
                        connections.push({ start: globeParticles[i].position, end: globeParticles[j].position, color: globeParticles[i].userData.packetColor });
                    }
                }
            }
            
            globeLineMesh.geometry.dispose();
            const lineGeo = new THREE.BufferGeometry();
            lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
            globeLineMesh.geometry = lineGeo;
            
            for (let k = 0; k < 5; k++) {
                if (Math.random() > 0.5 && connections.length > 0) {
                    const route = connections[Math.floor(Math.random() * connections.length)];
                    globeActivePackets.push({ start: route.start, end: route.end, progress: 0, speed: 0.01 + Math.random() * 0.02, color: new THREE.Color(route.color) });
                }
            }
            
            const packetPositions = [];
            const packetColorsArr = [];
            
            for (let i = globeActivePackets.length - 1; i >= 0; i--) {
                const pkt = globeActivePackets[i];
                pkt.progress += pkt.speed;
                if (pkt.progress >= 1) { globeActivePackets.splice(i, 1); continue; }
                const x = THREE.MathUtils.lerp(pkt.start.x, pkt.end.x, pkt.progress);
                const y = THREE.MathUtils.lerp(pkt.start.y, pkt.end.y, pkt.progress);
                const z = THREE.MathUtils.lerp(pkt.start.z, pkt.end.z, pkt.progress);
                packetPositions.push(x, y, z);
                packetColorsArr.push(pkt.color.r, pkt.color.g, pkt.color.b);
            }
            
            packetGeo.setAttribute('position', new THREE.Float32BufferAttribute(packetPositions, 3));
            packetGeo.setAttribute('color', new THREE.Float32BufferAttribute(packetColorsArr, 3));
            
            globeRenderer.render(globeScene, globeCamera);
        };
        
        animateGlobe();
        
        // Resize handler for responsive globe
        const handleGlobeResize = () => {
            if (!globeRenderer || !globeCamera || !mainGlobeContainer) return;
            
            const containerRect = mainGlobeContainer.getBoundingClientRect();
            const newSize = Math.min(containerRect.width, containerRect.height) * 0.9;
            
            globeRenderer.setSize(newSize, newSize);
            globeCamera.updateProjectionMatrix();
        };
        
        window.addEventListener('resize', handleGlobeResize);
    };
    
    // Web search animation - show globe, slide entire container down
    window.webSearchStart = () => {
        if (!mainGlobeContainer || !imageStreamContainer) return;
        
        initMainGlobe();
        mainGlobeContainer.classList.add('visible');
        imageStreamContainer.classList.add('web-active');
        
        // Trigger resize check after visibility transition
        setTimeout(() => {
            if (globeRenderer && globeCamera && mainGlobeContainer) {
                const containerRect = mainGlobeContainer.getBoundingClientRect();
                const newSize = Math.min(containerRect.width, containerRect.height) * 0.9;
                globeRenderer.setSize(newSize, newSize);
                globeCamera.updateProjectionMatrix();
            }
        }, 100);
    };
    
    // End web search animation - fade globe, slide container back up
    window.webSearchEnd = () => {
        if (!mainGlobeContainer || !imageStreamContainer) return;
        
        mainGlobeContainer.classList.remove('visible');
        imageStreamContainer.classList.remove('web-active');
    };

    // ============================================
    // SHELL TERMINAL ANIMATION
    // ============================================
    
    const shellTerminalContainer = document.getElementById('shellTerminalContainer');
    const shellCmdText = document.getElementById('shellCmdText');
    const shellStreamLine = document.getElementById('shellStreamLine');
    const shellStreamText = document.getElementById('shellStreamText');
    const shellStatusLine = document.getElementById('shellStatusLine');
    const shellStatusTag = document.getElementById('shellStatusTag');
    const shellStatusText = document.getElementById('shellStatusText');
    const shellTermTitle = document.getElementById('shellTermTitle');
    const shellCursor = document.getElementById('shellCursor');
    const shellProgress = document.getElementById('shellProgress');
    
    let shellStreamTimeout = null;
    let shellTextInterval = null;
    let shellResultInterval = null;

    const streamTextInto = (element, text, scrollContainer, onDone) => {
        element.textContent = '';
        let idx = 0;
        const step = Math.max(1, Math.floor(text.length / 60));
        const id = setInterval(() => {
            idx += step;
            if (idx >= text.length) {
                idx = text.length;
                clearInterval(id);
                if (onDone) onDone();
            }
            element.textContent = text.substring(0, idx);
            if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }, 25);
        return id;
    };

    const resetShellTerminal = () => {
        // Reset all lines to hidden
        if (shellStreamLine) { shellStreamLine.classList.remove('visible'); }
        if (shellStatusLine) { shellStatusLine.classList.remove('visible'); }
        
        // Reset content
        if (shellTermTitle) shellTermTitle.textContent = 'Shell';
        if (shellCmdText) shellCmdText.textContent = 'autouse.';
        if (shellStreamText) shellStreamText.textContent = '';
        if (shellStatusText) shellStatusText.textContent = 'running';
        
        // Reset tag to running state
        if (shellStatusTag) {
            shellStatusTag.className = 'tag run';
            shellStatusTag.textContent = '●';
        }
        
        // Show cursor and progress
        if (shellCursor) shellCursor.style.display = '';
        if (shellProgress) shellProgress.style.display = '';
        
        // Clear any pending stream timeout / intervals
        if (shellStreamTimeout) {
            clearTimeout(shellStreamTimeout);
            shellStreamTimeout = null;
        }
        if (shellTextInterval) {
            clearInterval(shellTextInterval);
            shellTextInterval = null;
        }
        if (shellResultInterval) {
            clearInterval(shellResultInterval);
            shellResultInterval = null;
        }
    };
    
    // Shell start: terminal card appears, screenshot slides down
    window.shellStart = (command, label) => {
        if (!shellTerminalContainer || !imageStreamContainer) return;

        resetShellTerminal();

        // Set the terminal title (Shell or AppleScript)
        if (shellTermTitle) shellTermTitle.textContent = label || 'Shell';

        // Set the command text
        if (shellCmdText) shellCmdText.textContent = 'autouse.';
        
        // Show container + push screenshot down
        shellTerminalContainer.classList.add('visible');
        imageStreamContainer.classList.add('shell-active');
        
        // Animate stream line after short delay — stream text progressively
        setTimeout(() => {
            if (shellStreamLine) {
                shellStreamLine.classList.add('visible');
                shellTextInterval = streamTextInto(
                    shellStreamText,
                    command || 'executing...',
                    shellStreamLine
                );
            }
        }, 300);

        // Show running status after short delay
        setTimeout(() => {
            if (shellStatusLine) shellStatusLine.classList.add('visible');
        }, 600);
    };
    
    // Shell result: show success or failure
    window.shellResult = (status, output) => {
        if (!shellTerminalContainer) return;
        
        // Hide cursor and progress bar
        if (shellCursor) shellCursor.style.display = 'none';
        if (shellProgress) shellProgress.style.display = 'none';
        
        // Truncate output for display (keep it short)
        const displayOutput = output ? (output.length > 80 ? output.substring(0, 80) + '...' : output) : '';
        
        if (status === 'success') {
            if (shellStatusTag) {
                shellStatusTag.className = 'tag ok';
                shellStatusTag.textContent = '✓';
            }
            if (shellStatusText) {
                shellResultInterval = streamTextInto(
                    shellStatusText,
                    displayOutput || 'completed',
                    shellStatusLine
                );
            }
        } else {
            if (shellStatusTag) {
                shellStatusTag.className = 'tag fail';
                shellStatusTag.textContent = '✗';
            }
            if (shellStatusText) {
                shellStatusText.style.color = 'rgba(70, 70, 70, 0.95)';
                shellResultInterval = streamTextInto(
                    shellStatusText,
                    displayOutput || 'failed',
                    shellStatusLine
                );
            }
        }
    };
    
    // Shell end: terminal card fades out, screenshot slides back up
    window.shellEnd = () => {
        if (!shellTerminalContainer || !imageStreamContainer) return;
        
        shellTerminalContainer.classList.remove('visible');
        imageStreamContainer.classList.remove('shell-active');
        
        // Reset color after fade out completes
        setTimeout(() => {
            if (shellStatusText) shellStatusText.style.color = '';
            resetShellTerminal();
        }, 700);
    };
});
