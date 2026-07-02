import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function ConversationSidebar({
  selectedConversationId,
  onSelectConversation,
  onNewConversation,
  refreshToken,
}) {
  
  const [recentConversations, setRecentConversations] = useState([]);

  const [archivedConversations, setArchivedConversations] = useState([]);

  const [menuConversationId, setMenuConversationId] = useState(null);

  const [searchText, setSearchText] = useState("");

  async function loadConversations() {
    try {
        const data =
        await api.listConversations(true);

        setRecentConversations(
        data.filter(
            (c) => !c.archived
        )
        );

        setArchivedConversations(
        data.filter(
            (c) => c.archived
        )
        );
    } catch (err) {
      console.error(err);
    }
  }

    useEffect(() => {
        loadConversations();
    }, [refreshToken]);

  
    useEffect(() => {
    function handleClick() {
        setMenuConversationId(null);
    }

    document.addEventListener(
        "click",
        handleClick
    );

    return () =>
        document.removeEventListener(
        "click",
        handleClick
        );
    }, []);

    const filteredRecentConversations =
    recentConversations.filter(
        (conversation) =>
        conversation.title
            .toLowerCase()
            .includes(
            searchText.toLowerCase()
            )
    );

    const filteredArchivedConversations =
    archivedConversations.filter(
        (conversation) =>
        conversation.title
            .toLowerCase()
            .includes(
            searchText.toLowerCase()
            )
    );

  return (
    <aside className="conversation-sidebar">
      <button
        className="new-chat-btn"
        onClick={onNewConversation}
      >
        + New conversation
      </button>
        <div className="conversation-search">
        <input
            type="text"
            placeholder="Search conversations..."
            value={searchText}
            onChange={(event) =>
            setSearchText(
                event.target.value
            )
            }
        />

        {searchText && (
            <button
            className="search-clear-btn"
            onClick={() =>
                setSearchText("")
            }
            >
            ×
            </button>
        )}
        </div>
      <div className="conversation-section">
        <div className="conversation-section-title">
          Recents
        </div>

        {filteredRecentConversations.map(
          (conversation) => (
            <div 
                key={conversation.id}
                className="conversation-row"
            >
            <button
                className={`conversation-item ${
                selectedConversationId ===
                conversation.id
                    ? "active"
                    : ""
                }`}
                title={conversation.title}
                onClick={() =>
                onSelectConversation(
                    conversation.id
                )
                }
            >
                {conversation.title}
            </button>

            <button
            className="conversation-menu-btn"
            onClick={(event) => {
                event.stopPropagation();

                setMenuConversationId(
                menuConversationId ===
                conversation.id
                    ? null
                    : conversation.id
                );
            }}
            >
            ⋮
            </button>

            {menuConversationId ===
            conversation.id && (
            <div
                className="conversation-menu"
            >
                <button
                onClick={async () => {
                    const title =
                    prompt(
                        "Rename conversation",
                        conversation.title
                    );

                    if (!title) {
                    return;
                    }

                    await api.renameConversation(
                    conversation.id,
                    title
                    );

                    await loadConversations();

                    setMenuConversationId(
                    null
                    );
                }}
                >
                Rename
                </button>

                <button
                    onClick={async () => {
                    await api.archiveConversation(
                        conversation.id
                    );

                    await loadConversations();

                    setMenuConversationId(null);

                    if (
                        selectedConversationId ===
                        conversation.id
                    ) {
                        onNewConversation();
                    }
                    }}
                >
                    Archive
                </button>

                <button
                    className="danger"
                    onClick={async () => {
                    const confirmed = window.confirm(
                        "Delete this conversation?"
                    );

                    if (!confirmed) {
                        return;
                    }

                    await api.deleteConversation(
                        conversation.id
                    );

                    await loadConversations();

                    setMenuConversationId(null);

                    if (
                        selectedConversationId ===
                        conversation.id
                    ) {
                        onNewConversation();
                    }
                    }}
                >
                    Delete
                </button>

            </div>
            )}
            </div>
          )
        )}

        {searchText &&
        filteredRecentConversations.length === 0 &&
        filteredArchivedConversations.length === 0 && (
        <div className="conversation-empty">
            No conversations found
        </div>
        )}

        {filteredArchivedConversations.length > 0 && (
        <>
            <div className="conversation-section-title">
            Archived
            </div>

            {archivedConversations.map(
            (conversation) => (
                <div
                key={conversation.id}
                className="conversation-row"
                >
                <button
                    className={`conversation-item ${
                    selectedConversationId ===
                    conversation.id
                        ? "active"
                        : ""
                    }`}
                    title={conversation.title}
                    onClick={() =>
                    onSelectConversation(
                        conversation.id
                    )
                    }
                >
                    {conversation.title}
                </button>

                <button
                    className="conversation-menu-btn"
                    onClick={(event) => {
                    event.stopPropagation();

                    setMenuConversationId(
                        menuConversationId ===
                        conversation.id
                        ? null
                        : conversation.id
                    );
                    }}
                >
                    ⋮
                </button>

                {menuConversationId ===
                    conversation.id && (
                    <div
                    className="conversation-menu"
                    >
                        <button
                        onClick={async () => {
                            const title = prompt(
                            "Rename conversation",
                            conversation.title
                            );

                            if (!title) {
                            return;
                            }

                            await api.renameConversation(
                            conversation.id,
                            title
                            );

                            await loadConversations();

                            setMenuConversationId(
                            null
                            );
                        }}
                        >
                        Rename
                        </button>

                        <button
                        onClick={async () => {
                            await api.unarchiveConversation(
                            conversation.id
                            );

                            await loadConversations();

                            setMenuConversationId(
                            null
                            );
                        }}
                        >
                        Unarchive
                        </button>

                        <button
                        className="danger"
                        onClick={async () => {
                            const confirmed =
                            window.confirm(
                                "Delete this conversation?"
                            );

                            if (!confirmed) {
                            return;
                            }

                            await api.deleteConversation(
                            conversation.id
                            );

                            await loadConversations();

                            setMenuConversationId(
                            null
                            );

                            if (
                            selectedConversationId ===
                            conversation.id
                            ) {
                            onNewConversation();
                            }
                        }}
                        >
                        Delete
                        </button>
                        
                    </div>
                )}
                </div>
            )
            )}


        </>
        )}


      </div>
    </aside>
  );
}