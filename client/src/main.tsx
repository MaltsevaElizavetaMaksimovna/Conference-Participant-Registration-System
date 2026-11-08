import {createRoot} from "react-dom/client";
import {BrowserRouter, Route, Routes} from "react-router";
import {Provider} from "react-redux";
import {UserPanel} from "./pages/UserPanel";
import {AdminPanel} from "./pages/AdminPanel";
import {store} from "./store/store";
import "./styles/app.css"
import {RequireAuth} from "~/modules/AdminModule/components/RequireAuth";
import {LoginPanel} from "~/pages/LoginPanel";

createRoot(document.getElementById("root")!).render(
    <Provider store={store}>
        <BrowserRouter>
            <Routes>
                <Route index element={<UserPanel/>}></Route>
                <Route path='login' element={<LoginPanel/>}></Route>
                <Route path='admin' element={<RequireAuth/>}>
                    <Route index element={<AdminPanel/>}></Route>
                </Route>
            </Routes>
        </BrowserRouter>
    </Provider>
);