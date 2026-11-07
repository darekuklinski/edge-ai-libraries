import classes from "./Navbar.module.scss"
import { SYSTEM_INFO } from "../../config";
import { Button, Menu } from "@mantine/core";

type NavbarProps = {
    username: string;
    onSettings: () => void;
    onLogout: () => void;
};

export function Navbar({ username, onSettings, onLogout }: NavbarProps) {
    const systemInfo = [
        SYSTEM_INFO.cpu && `CPU: ${SYSTEM_INFO.cpu}`,
        SYSTEM_INFO.gpu && `GPU: ${SYSTEM_INFO.gpu}`,
        SYSTEM_INFO.ram && `RAM: ${SYSTEM_INFO.ram}`,
        SYSTEM_INFO.os && `OS: ${SYSTEM_INFO.os}`,
    ].filter(Boolean).join(" | ");

    return (
        <header className={classes.navbar}>
            <div className={classes.navLeft}>
                <img className={classes.logo} src="/Intel_logo.svg" alt="Intel" />
                <span className={classes.navTitle}>Chat QnA</span>
            </div>
            {systemInfo && (
                <div className={classes.systemInfo} title={systemInfo}>
                    {systemInfo}
                </div>
            )}
            <div className={classes.navRight}>
                <Menu position="bottom-end" withinPortal>
                    <Menu.Target>
                        <Button className={classes.username} variant="subtle" size="compact-sm">
                            {username}
                        </Button>
                    </Menu.Target>
                    <Menu.Dropdown>
                        <Menu.Item onClick={onSettings}>Settings</Menu.Item>
                        <Menu.Item color="red" onClick={onLogout}>Log out</Menu.Item>
                    </Menu.Dropdown>
                </Menu>
            </div>
        </header>
    )
}