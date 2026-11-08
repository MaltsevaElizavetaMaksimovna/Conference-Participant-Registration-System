import {createRoot} from "react-dom/client";
import {BrowserRouter, Route, Routes} from "react-router";
import {Provider} from "react-redux";
import {UserPanel} from "./pages/UserPanel";
import {AdminPanel} from "./pages/AdminPanel";
import {store} from "./store/store";
import "./styles/app.css"
import {RequireAuth} from "~/modules/AdminModule/components/RequireAuth";
import {LoginPanel} from "~/pages/LoginPanel";
import {AdminImport} from "~/modules/AdminModule/components/AdminImport";
import {AdminLayout} from "~/modules/AdminModule/components/AdminLayout";
import {AdminSettings} from "~/modules/AdminModule/components/AdminSettings";

createRoot(document.getElementById("root")!).render(
    <Provider store={store}>
        <BrowserRouter>
            <Routes>
                <Route index element={<UserPanel/>}></Route>
                <Route path='login' element={<LoginPanel/>}></Route>
                <Route path='admin' element={<RequireAuth/>}>
                    <Route element={<AdminLayout/>}>
                        <Route index element={<AdminPanel/>}/>
                        <Route path='import' element={<AdminImport/>}/>
                        <Route path='settings' element={<AdminSettings/>}/>
                    </Route>

                </Route>
            </Routes>
        </BrowserRouter>
    </Provider>
);