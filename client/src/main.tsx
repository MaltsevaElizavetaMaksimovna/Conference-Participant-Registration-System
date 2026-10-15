import {createRoot} from "react-dom/client";
import {BrowserRouter, Route, Routes} from "react-router";
import {Provider} from "react-redux";
import {UserPanel} from "./pages/UserPanel";
import {AdminPanel} from "./pages/AdminPanel";
import {store} from "./store/store";
import "./styles/app.css"

createRoot(document.getElementById("root")!).render(
    <Provider store={store}>
    <BrowserRouter>
        <Routes>
            <Route index element={<UserPanel/>}></Route>
            <Route path='admin' element={<AdminPanel/>}></Route>
        </Routes>
    </BrowserRouter>
    </Provider>
);