import {useEffect} from 'react';
import {useAppDispatch} from '~/hooks/redux';
import {scanCode} from '~/store/reducers/TerminalSlice';

// USB-сканер передаёт физические клавиши US-клавиатуры даже при русской раскладке Windows.
const punctuation: Record<string, string> = {
    Minus: '-_', Equal: '=+', BracketLeft: '[{', BracketRight: ']}',
    Backslash: '\\|', Semicolon: ';:', Quote: "'\"", Backquote: '`~',
    Comma: ',<', Period: '.>', Slash: '/?', Space: '  ',
};

function scanCharacter(event: KeyboardEvent): string {
    if (/^Key[A-Z]$/.test(event.code)) {
        const letter = event.code.slice(-1);
        return event.shiftKey ? letter : letter.toLowerCase();
    }
    if (/^Digit[0-9]$/.test(event.code)) {
        const digit = event.code.slice(-1);
        return event.shiftKey ? ')!@#$%^&*('[Number(digit)] : digit;
    }
    return punctuation[event.code]?.[Number(event.shiftKey)] ?? '';
}

export function useUsbScanner(enabled: boolean) {
    const dispatch = useAppDispatch();
    useEffect(() => {
        if (!enabled) return;
        let buffer = '';
        let tooLong = false;
        const clear = () => { buffer = ''; tooLong = false; };
        const read = (event: KeyboardEvent) => {
            if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
            if (event.key === 'Enter') {
                if (buffer && !tooLong) {
                    event.preventDefault();
                    dispatch(scanCode(buffer));
                }
                clear();
                return;
            }
            if (event.key === 'Escape') { clear(); return; }
            const character = scanCharacter(event);
            if (!character) return;
            event.preventDefault();
            if (buffer.length < 2000) buffer += character;
            else tooLong = true;
        };
        window.addEventListener('keydown', read);
        window.addEventListener('blur', clear);
        return () => {
            window.removeEventListener('keydown', read);
            window.removeEventListener('blur', clear);
        };
    }, [dispatch, enabled]);
}
