import React from "react";

interface TerminalBlockProps {
    children?: React.ReactNode;
    sectionTitle: string;
}

export const TerminalBlock = ({sectionTitle, children}: TerminalBlockProps) => {
    return (
        <div className="section">
            <div className="section_title">{sectionTitle}</div>
            <div className="section_body">
                <div className="terminal_header"><span className="dot"></span> Терминал №1 · онлайн</div>
                {children}
            </div>
        </div>
    );
};
